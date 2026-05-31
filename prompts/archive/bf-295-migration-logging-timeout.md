# BF-295 — Configurable per-migration timeout + elapsed-time logging

**Status:** Ready for Builder
**Dependencies:** Existing `MemoryConfig` (config.py:828), existing migration block in `cognitive_services.py` (lines ~191–340), commit `44c80c70` (start-of-migration logging + hardcoded 120s timeout) already in HEAD.
**Estimated tests:** 5+ new tests; full backend regression must stay green.
**Closes:** #748

---

## Problem

Issue #748 reports that `cognitive_services.py` runs 6 episodic-memory migrations (AD-541f, BF-103, AD-570, AD-570b, AD-584, AD-605) and one of them — most likely AD-605 enriched re-embed — hangs indefinitely on a data dir with many episodes. No start log, no progress, no timeout.

Commit `44c80c70` ("BF-AD-748: PROBOS_SKIP_EPISODIC_MIGRATIONS escape hatch + start-of-migration logging") partially addressed this by:
- Logging `logger.info("<name>: starting ...")` before each migration call.
- Wrapping each migration in `asyncio.wait_for(..., timeout=_MIGRATION_TIMEOUT_S)` with `_MIGRATION_TIMEOUT_S = 120.0` hardcoded.
- Adding a `PROBOS_SKIP_EPISODIC_MIGRATIONS=1` operator escape hatch.

**Remaining gaps:**

1. **Timeout is hardcoded at 120s.** AD-605 enriched re-embed on a real CPU-bound store with 10k+ episodes can legitimately need 5–15 minutes. 120s honest-degrades a migration that would have completed in 4 minutes. Operator has no knob.
2. **No elapsed-time logging on success.** When an operator stares at a 5-minute boot, the journal currently shows "starting" with no end-of-migration timestamp. Hard to tell if a migration finished fast or whether it timed out silently (the warning is at WARNING level, easy to miss in a noisy boot).
3. **AD-541f eviction audit start is not timeout-guarded.** Lower priority — it's a service start, not a data migration — but it's the only remaining unbounded `await` in the migration block.

This BF closes those gaps. The investigative third point in the original issue body (shutdown partial consolidation leaving migrations stuck) is **out of scope** and stays in #748's discussion thread for a follow-on AD.

---

## Verified Against Codebase (2026-05-23)

```
grep -n "_MIGRATION_TIMEOUT_S" src/probos/startup/cognitive_services.py
  227:    _MIGRATION_TIMEOUT_S = 120.0
  262:                timeout=_MIGRATION_TIMEOUT_S,
  267:                "BF-103: Episode ID migration timed out after %.0fs (skipping)",
  281:                timeout=_MIGRATION_TIMEOUT_S,
  286:                "AD-570: Anchor metadata migration timed out after %.0fs (skipping)",
  305:                timeout=_MIGRATION_TIMEOUT_S,
  310:                "AD-570b: Participant index backfill timed out after %.0fs (skipping)",
  325:                timeout=_MIGRATION_TIMEOUT_S,
  330:                "AD-584: Embedding model migration timed out after %.0fs (skipping)",
  346:                timeout=_MIGRATION_TIMEOUT_S,
  351:                "AD-605: Enriched embedding migration timed out after %.0fs (skipping)",

grep -n "^class MemoryConfig" src/probos/config.py
  828: class MemoryConfig(BaseModel):

grep -n "shutdown_consolidation_timeout_s\|shutdown_drain_timeout_s" src/probos/config.py
  856:    shutdown_consolidation_timeout_s: float = 30.0
  862:    shutdown_drain_timeout_s: float = Field(

grep -rn "_memory_field" src/probos/
  (no matches — BF-291 helper does not exist; use direct config.memory.X access)
```

The five migrations under `_skip_migrations` are: BF-103 (line 252), AD-570 (270), AD-570b (290), AD-584 (320), AD-605 (340). AD-541f at line 218 is a service start, not a migration, and currently has no `asyncio.wait_for`.

---

## Solution

### Section 1 — Add `MemoryConfig.migration_timeout_s`

In `src/probos/config.py`, inside `MemoryConfig` (line 828), add a new field next to the existing AD-820/AD-825 shutdown timeout fields. Follow the AD-825 `Field(default=..., ge=..., le=..., description=...)` pattern verbatim.

```python
# SEARCH (anchor on the AD-825 field — it is unique in the class):
    # AD-825: max seconds to wait for write-holding background tasks
```

Insert immediately **before** the AD-825 block:

```python
    # BF-295 (#748): per-migration timeout for episodic-memory startup
    # migrations (BF-103, AD-570, AD-570b, AD-584, AD-605). Stuck or
    # CPU-bound migrations honest-degrade to a warning after this
    # ceiling and boot continues. Default 300s (5 min) — generous
    # enough for AD-605 enriched re-embed on a 10k-episode store on
    # CPU; operator can raise for very large stores or lower for
    # fast-restart workflows. Replaces the hardcoded 120.0 in
    # cognitive_services.py shipped with commit 44c80c70.
    migration_timeout_s: float = Field(
        default=300.0, ge=10.0, le=3600.0,
        description=(
            "BF-295 (#748): per-migration timeout in seconds for episodic-memory "
            "startup migrations. Stuck migrations honest-degrade after this "
            "ceiling. Default 300s; range 10s–3600s."
        ),
    )
```

### Section 2 — Replace the hardcoded `_MIGRATION_TIMEOUT_S` and add elapsed-time logging

In `src/probos/startup/cognitive_services.py`, the current pattern is:

```python
_MIGRATION_TIMEOUT_S = 120.0   # line 227 — REMOVE
...
logger.info("BF-103: starting episode agent_id migration")
migrated = await asyncio.wait_for(
    migrate_episode_agent_ids(episodic_memory, identity_registry),
    timeout=_MIGRATION_TIMEOUT_S,
)
if migrated > 0:
    logger.info("BF-103: Migrated %d episodes to sovereign IDs", migrated)
except asyncio.TimeoutError:
    logger.warning(
        "BF-103: Episode ID migration timed out after %.0fs (skipping)",
        _MIGRATION_TIMEOUT_S,
    )
except Exception:
    logger.warning("BF-103: Episode ID migration failed (non-fatal)", exc_info=True)
```

#### 2a. Replace the module-local constant with a config read

```python
# SEARCH:
    # BF (2026-05-22, #748): each episodic-memory migration below now
    # logs a start message AND runs under asyncio.wait_for so a stuck
    # migration honest-degrades to a warning instead of bricking boot.
    # Generous 120s ceiling — enough for hundreds of episodes; well
    # below the operator's typical patience threshold.
    _MIGRATION_TIMEOUT_S = 120.0
```

```python
# REPLACE WITH:
    # BF-295 (#748): each episodic-memory migration below logs start +
    # elapsed time AND runs under asyncio.wait_for. Timeout sourced from
    # config.memory.migration_timeout_s (default 300s) so the operator
    # can raise it for large stores (AD-605 enriched re-embed on a 10k+
    # store can legitimately need several minutes on CPU). Honest-degrade
    # to WARNING on timeout; boot continues.
    _migration_timeout_s = float(config.memory.migration_timeout_s)
```

#### 2b. Rewrite each of the five `asyncio.wait_for` blocks to log elapsed time on success and reference the new variable

Apply the following pattern to each of the five migration blocks (BF-103, AD-570, AD-570b, AD-584, AD-605). Use `time.perf_counter()` for elapsed measurement — `time` is already imported (cognitive_services.py:12).

**Pattern (use for each migration; tag the labels and migration calls verbatim from the current code):**

```python
# SEARCH (BF-103 example — apply the same shape to every migration):
            from probos.cognitive.episodic import migrate_episode_agent_ids
            logger.info("BF-103: starting episode agent_id migration")
            migrated = await asyncio.wait_for(
                migrate_episode_agent_ids(episodic_memory, identity_registry),
                timeout=_MIGRATION_TIMEOUT_S,
            )
            if migrated > 0:
                logger.info("BF-103: Migrated %d episodes to sovereign IDs", migrated)
        except asyncio.TimeoutError:
            logger.warning(
                "BF-103: Episode ID migration timed out after %.0fs (skipping)",
                _MIGRATION_TIMEOUT_S,
            )
        except Exception:
            logger.warning("BF-103: Episode ID migration failed (non-fatal)", exc_info=True)
```

```python
# REPLACE WITH:
            from probos.cognitive.episodic import migrate_episode_agent_ids
            logger.info("BF-103: starting episode agent_id migration (timeout=%.0fs)", _migration_timeout_s)
            _t0 = time.perf_counter()
            migrated = await asyncio.wait_for(
                migrate_episode_agent_ids(episodic_memory, identity_registry),
                timeout=_migration_timeout_s,
            )
            _elapsed = time.perf_counter() - _t0
            if migrated > 0:
                logger.info("BF-103: Migrated %d episodes to sovereign IDs in %.1fs", migrated, _elapsed)
            else:
                logger.info("BF-103: episode agent_id migration completed in %.1fs (no episodes needed migration)", _elapsed)
        except asyncio.TimeoutError:
            logger.warning(
                "BF-103: Episode ID migration timed out after %.0fs — proceeding with degraded state",
                _migration_timeout_s,
            )
        except Exception:
            logger.warning("BF-103: Episode ID migration failed (non-fatal)", exc_info=True)
```

Apply the same shape (start log with timeout, perf_counter wrap, elapsed-time log on success, TimeoutError warning referencing `_migration_timeout_s`, generic Exception with `exc_info=True`) to:

- **AD-570** (anchor metadata migration) — line ~270
- **AD-570b** (participant index backfill) — line ~290; do NOT replace the surrounding `participant_index.start()` line, only the `migrate_participant_index` block
- **AD-584** (embedding model migration) — line ~320
- **AD-605** (enriched embedding migration) — line ~340; note this one already runs inside `loop.run_in_executor`, keep that intact

For each block, preserve the exact label text ("AD-570", "AD-570b", etc.) and the current "Migrated N episodes" success message — just add the `_elapsed` formatting and switch `_MIGRATION_TIMEOUT_S` → `_migration_timeout_s`.

#### 2c. Out of scope — do NOT touch

- AD-541f eviction audit start (line 218) — service start, not a migration. The hang report points at AD-605; widening scope creates surface area without evidence.
- BF-207 hash integrity sweep (line ~360) — already non-blocking by design; not part of the five `_skip_migrations` block.
- `PROBOS_SKIP_EPISODIC_MIGRATIONS` env var path — unchanged.
- The investigative third point in #748 (shutdown consolidation leaving migrations stuck) — separate AD.

---

## Tests

Create `tests/test_bf295_migration_timeouts.py`. Five test cases:

1. **`test_migration_timeout_config_default_is_300s`** — `SystemConfig().memory.migration_timeout_s == 300.0`.
2. **`test_migration_timeout_config_validates_range`** — pydantic rejects `migration_timeout_s=5.0` and `migration_timeout_s=4000.0`; accepts `migration_timeout_s=300.0` and the boundary values `10.0` and `3600.0`.
3. **`test_migration_start_message_logged_before_call`** — patch `migrate_episode_agent_ids` with a `MagicMock(return_value=0)` async wrapper; call `init_cognitive_services` (or a smaller carved-out helper if available) with `caplog.at_level(logging.INFO, logger="probos.startup.cognitive_services")`; assert "BF-103: starting episode agent_id migration" appears in the log records **before** the patched mock is awaited (use a side_effect that records `time.perf_counter()` at await time and compare to the log record's `created` field, OR just assert the message appears at all and the mock was awaited once — the start-message assertion is the load-bearing one).
4. **`test_migration_timeout_logs_warning_and_does_not_raise`** — patch `migrate_episode_agent_ids` with an async function that `await asyncio.sleep(10.0)`; set `config.memory.migration_timeout_s = 0.05`; assert the surrounding `init_cognitive_services` call returns normally (does not raise), and that a WARNING log record contains "timed out after 0s — proceeding with degraded state" (use `%.0f`-formatted output).
5. **`test_migration_success_logs_elapsed_time`** — patch `migrate_episode_agent_ids` to return 7 instantly; assert INFO log contains "BF-103: Migrated 7 episodes to sovereign IDs in" followed by a numeric `Ns` suffix (regex: `r"Migrated 7 episodes .* in \d+\.\d+s"`).

**Optional sixth test (recommended):** `test_migration_unexpected_exception_logs_with_traceback` — patch the migration to raise `RuntimeError("synthetic")`; assert WARNING log with `exc_info` populated (caplog records have `.exc_info` on them) and call returns normally.

### Test-author notes (so the Builder doesn't churn)

- `init_cognitive_services` is large and has many side effects. The cleanest mock surface is to patch `probos.cognitive.episodic.migrate_episode_agent_ids` (and friends) at the module path **before** `init_cognitive_services` is called, then drive a single migration block. If a tighter seam isn't reachable without refactoring, the Builder may carve a small helper `_run_one_migration(name, coro_factory, timeout_s, success_template)` and unit-test that helper directly — both shapes are acceptable. Prefer the helper if `init_cognitive_services` requires more than ~6 mocks to instantiate.
- Use `pytest.LogCaptureFixture` (`caplog`) with `caplog.set_level(logging.INFO, logger="probos.startup.cognitive_services")`.
- `time.perf_counter` does not need to be monkey-patched; just give the patched migration a small `await asyncio.sleep(0.01)` so the elapsed-time log has a non-zero number to format.

---

## What This Does NOT Change

- The `PROBOS_SKIP_EPISODIC_MIGRATIONS` operator escape hatch (44c80c70) is preserved verbatim.
- AD-541f eviction audit log start is NOT wrapped in `asyncio.wait_for`. Out of scope; service start, not a migration.
- BF-207 hash integrity sweep is NOT touched. It's after the `_skip_migrations` block and already non-fatal.
- No new environment variables. The knob is `config.memory.migration_timeout_s` in `system.yaml`.
- The investigative shutdown-consolidation-leaving-migrations-stuck question stays in issue #748's thread; a follow-on AD owns it.
- No changes to migration code in `probos.cognitive.episodic` itself — this BF is purely the startup wrapper.

---

## Acceptance Criteria

- [ ] `MemoryConfig.migration_timeout_s` exists with default 300.0, `ge=10.0`, `le=3600.0`, and a description that names BF-295 + #748.
- [ ] `_MIGRATION_TIMEOUT_S = 120.0` is removed from `cognitive_services.py`. All five migrations read `config.memory.migration_timeout_s` (via local `_migration_timeout_s` shadow).
- [ ] Each of the five migrations logs (a) a start message including the timeout in seconds, (b) an elapsed-time message on success, (c) a WARNING with "timed out after Ns — proceeding with degraded state" on `asyncio.TimeoutError`, (d) a WARNING with `exc_info=True` on any other exception.
- [ ] 5+ new tests in `tests/test_bf295_migration_timeouts.py` pass.
- [ ] Existing AD-820..AD-826 regression tests stay green.
- [ ] Full backend test gate green: `pytest tests/ -q -n 4 --dist=loadfile` (parallel) AND any AD-820..AD-826 test files re-run at `-n 0` to confirm not order-dependent.
- [ ] No UI/vitest changes needed.
- [ ] One commit message: `BF-295: configurable per-migration timeout + elapsed-time logging\n\nCloses #748`.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Standing Constraints

- **DO NOT** touch the live runtime under `C:\Users\seang\AppData\Local\ProbOS\`. All tests run against `tmp_path` or in-memory fixtures.
- **DO NOT** broaden the scope to AD-541f, BF-207, or the shutdown consolidation question. Those stay in #748 for a follow-on AD.
- **DO NOT** introduce a `_memory_field` defensive helper — no such helper exists in the codebase (verified 2026-05-23). Use direct `config.memory.migration_timeout_s` access. If a future BF needs the defensive pattern, it lands as its own AD.
- **DO NOT** rename or reformat unrelated lines in `cognitive_services.py` — keep the diff tight.
- **DO NOT** drop the `PROBOS_SKIP_EPISODIC_MIGRATIONS` escape hatch.

---

## Background Reference

Alembic (SQLAlchemy migrations) and Django South both ship per-migration `--timeout` knobs with start/end log lines specifically because the alternative — a silent hang — is the worst possible operator experience for boot-time data migrations. The 300s default mirrors Alembic's typical operator-friendly default (5min). This BF brings ProbOS's episodic-memory migrations in line with that industry baseline.
