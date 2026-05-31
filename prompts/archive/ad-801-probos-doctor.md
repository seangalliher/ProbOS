# AD-801 — `probos doctor` Pluggable Check Registry + Missing Checks

**Issue:** [#725](https://github.com/seangalliher/ProbOS/issues/725)
**Wave:** 188
**Author:** Architect (sole-author small-AD fast path; no formal review_1/review_2 gates per Wave 187 precedent)
**Estimated tests added:** ~10

## Scope correction (verify-first save)

The original `_cmd_doctor` was filed as new in the AD-801 issue, but it **already exists** at `src/probos/__main__.py:984-1100` (shipped under AD-484 — UX & adoption). It performs 6 checks: config file, data_dir writable, LLM tier reachability, NATS, ChromaDB import, AD-711 security profile.

AD-801's revised real scope:

1. **Refactor the inline checks into a pluggable registry** so AD-798 (sandbox), AD-803..807 (channels), and AD-808 (migration) can each register their own checks without editing `__main__.py`. This is the architectural value of the AD.
2. **Add the missing checks** the existing impl doesn't cover:
   - Disk space (data_dir free GB; WARN below 1 GB, FAIL below 100 MB)
   - Episodic store consistency (open the ChromaDB collection; count episodes; basic open-without-error sanity)
   - Federation peers reachable (when `config.federation.enabled` and peers configured)
   - Overlay extension status (AD-697 `is_commercial_loaded()` + `loaded_providers()`)
   - Sandbox backend availability (AD-798 forward — for now: docker-daemon reachable check only when `config.security.sandbox_backend == "container"`; informational otherwise)
3. **Preserve the existing 6 checks unchanged** — moving them into the registry must not regress behavior.

## File layout

Create `src/probos/doctor/` package:

- `__init__.py` — re-exports `run_doctor(args, console) -> int` and the `DoctorCheck` protocol.
- `protocol.py` — defines:
  - `class CheckOutcome(Enum): OK / WARN / FAIL`
  - `@dataclass class CheckResult: outcome, message, remediation`
  - `class DoctorCheck(Protocol): name; async def run(ctx: DoctorContext) -> CheckResult`
  - `class DoctorContext: config, console, home_dir, data_dir` (passed to every check; immutable)
- `registry.py` — `register_check(check)`, `iter_checks()` over a module-level list; idempotent.
- `runner.py` — `async def run_doctor(args, console) -> int`: builds context, iterates checks in registration order, renders each result, returns total FAIL count.
- `checks/__init__.py` — calls `register_check` for each built-in check at import time.
- `checks/config_check.py` — preserves existing config-file + data-dir checks.
- `checks/llm_check.py` — preserves existing LLM tier check.
- `checks/nats_check.py` — preserves existing NATS check.
- `checks/chroma_check.py` — preserves existing ChromaDB import check + adds episodic-collection open sanity.
- `checks/security_check.py` — preserves existing AD-711 security profile check.
- `checks/disk_check.py` — NEW. `shutil.disk_usage(data_dir).free` → OK / WARN <1GB / FAIL <100MB.
- `checks/federation_check.py` — NEW. When `config.federation` is enabled and peers list non-empty: TCP-probe each peer. WARN per-peer unreachable; FAIL only if NO peers reachable.
- `checks/overlay_check.py` — NEW. Calls `probos.extensions.overlay.is_commercial_loaded()` + `loaded_providers()`; OK with info line listing providers, or OK with "OSS-only mode" line when none.
- `checks/sandbox_check.py` — NEW. Reads `config.security.sandbox_backend`. If `"container"`: probe docker daemon via subprocess `docker info` (timeout 3s) — OK on success / FAIL with install pointer on missing. If `"inprocess"` (default): info line only ("running in-process; AD-798 ContainerSandbox not active").

## `_cmd_doctor` becomes a 3-line thin shim

```python
def _cmd_doctor(args: argparse.Namespace) -> int:
    """Handle `probos doctor` -- delegates to doctor.run_doctor (AD-801)."""
    from probos.doctor import run_doctor
    return asyncio.run(run_doctor(args, Console()))
```

## Test plan (`tests/test_ad801_doctor.py`)

10 tests, all `-n 0`-safe:

1. `DoctorCheck` protocol satisfied by all built-in checks (structural subtyping check).
2. `register_check` is idempotent; double-registering the same `name` raises.
3. `run_doctor` returns 0 when every check reports OK.
4. `run_doctor` returns the FAIL count when some checks fail.
5. WARN does NOT increment the FAIL count.
6. `disk_check` returns FAIL at <100MB free (mock `shutil.disk_usage`).
7. `disk_check` returns WARN at <1GB free.
8. `overlay_check` reports `is_commercial_loaded()=True` path correctly (mock the overlay function).
9. `sandbox_check` reports docker-missing FAIL when `sandbox_backend="container"` and the `docker info` subprocess fails.
10. Existing AD-484 / AD-claude-bootstrap doctor tests still pass without modification (regression gate).

## Acceptance

- `probos doctor` on a healthy install prints all checks in OK state with the new ones visible; exits 0.
- Killing NATS in config-enabled mode produces a FAIL for NATS (existing behavior preserved).
- Setting `config.security.sandbox_backend = "container"` without docker installed produces a FAIL for sandbox.
- Existing tests under `test_ad484_ux_adoption.py` and `test_claude_bootstrap_init_defaults.py` pass without changes (the inline `_cmd_doctor` impl can call `run_doctor` directly — same return code semantics).
- +10 new pytest in `tests/test_ad801_doctor.py`; runtime <1s.
- Full pytest gate stays non-decreasing.

## Out of scope

- A formal `--json` / `--quiet` output mode (forward marker — file as AD-801a if needed).
- Auto-fix mode (forward marker AD-801b).
- HTTP `/api/doctor` endpoint that surfaces in the HXI (forward marker AD-801c — pairs with AD-796 status line).

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
