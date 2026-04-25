# Build Prompt: Structural Integrity Field — SIF (AD-370)

## Parallel Build Info
- **Builder:** Builder 2 (worktree `d:\ProbOS-builder-2`)
- **File footprint:** `src/probos/sif.py` (NEW), `src/probos/runtime.py`, `tests/test_sif.py` (NEW)
- **No overlap with:** Builder 1 (UI-only: `ui/src/components/IntentSurface.tsx`)

## Context

"Medical detects damage. The SIF prevents structural failure."

The Structural Integrity Field is a lightweight runtime service that runs pure
assertion-based invariant checks on every heartbeat cycle. It catches corruption
(NaN trust scores, orphaned agents, weight explosion, stale indexes) before it
manifests as a user-visible failure. It does NOT use LLM calls — every check is
a simple Python assertion against in-memory data structures.

SIF is a **Ship's Computer function**, not an agent. It runs as a background
`asyncio.Task` in the runtime.

**Identified by:** Phase 32 roadmap item (Starship systems research, 2026-03-18)

---

## Changes

### File: `src/probos/sif.py` (NEW)

Create a `StructuralIntegrityField` class:

```python
class StructuralIntegrityField:
    """Continuous invariant checking — the ship's structural skeleton."""
```

**Constructor parameters:**
- `trust_network` — the runtime's `TrustNetwork` instance (or None)
- `intent_bus` — the runtime's `IntentBus` instance (or None)
- `hebbian_router` — the runtime's `HebbianRouter` instance (or None)
- `spawner` — the runtime's `AgentSpawner` instance (or None)
- `pool_manager` — the runtime's `PoolManager` instance (or None)
- `check_interval: float = 5.0` — seconds between checks

All parameters are optional (default None) so SIF works in minimal/test configs.

**Seven invariant checks** — each returns a `SIFCheckResult`:

```python
@dataclass
class SIFCheckResult:
    """Result of a single SIF invariant check."""
    name: str
    passed: bool
    details: str = ""
```

| Method | What it checks | How |
|--------|---------------|-----|
| `check_trust_bounds()` | All trust scores in [0.0, 1.0], no NaN/inf | Iterate `trust_network.all_scores()`, check `math.isfinite()` and range |
| `check_hebbian_bounds()` | Hebbian weights in reasonable range [-10.0, 10.0], no NaN/inf | Read `hebbian_router._weights.values()`, check bounds |
| `check_pool_consistency()` | Pool agents exist in spawner templates | For each pool, verify agent types are registered |
| `check_intent_bus_coherence()` | All subscriber agent IDs correspond to live agents | Read `intent_bus._subscribers`, verify against spawner/pool |
| `check_config_validity()` | Runtime config passes Pydantic re-validation | Try `config.model_validate(config.model_dump())` |
| `check_index_consistency()` | CodebaseIndex file entries reference existing files | Sample check: verify indexed paths are non-empty strings |
| `check_memory_integrity()` | EpisodicMemory and KnowledgeStore are readable | Try a lightweight read operation, catch exceptions |

**Aggregate method:**

```python
async def run_all_checks(self) -> SIFReport:
    """Run all invariant checks and return aggregate report."""
```

```python
@dataclass
class SIFReport:
    """Aggregate SIF health report."""
    checks: list[SIFCheckResult]
    timestamp: float  # time.monotonic()

    @property
    def health_pct(self) -> float:
        """Percentage of checks passing (0.0 to 100.0)."""
        if not self.checks:
            return 100.0
        return (sum(1 for c in self.checks if c.passed) / len(self.checks)) * 100.0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def violations(self) -> list[SIFCheckResult]:
        return [c for c in self.checks if not c.passed]
```

**Background loop:**

```python
async def start(self) -> None:
    """Start the periodic SIF check loop."""
    self._task = asyncio.create_task(self._check_loop())

async def stop(self) -> None:
    """Stop the SIF check loop."""
    if self._task:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

async def _check_loop(self) -> None:
    """Run checks every check_interval seconds."""
    while True:
        await asyncio.sleep(self._check_interval)
        report = await self.run_all_checks()
        if not report.all_passed:
            logger.warning(
                "SIF violation detected (%.0f%% integrity): %s",
                report.health_pct,
                "; ".join(v.details for v in report.violations),
            )
        self._last_report = report
```

**Properties:**
- `last_report` — returns the most recent `SIFReport` (or None if not yet run)

**Implementation notes:**
- Each check method should be defensive — if the subsystem reference is None
  (not configured), return a passing result with `details="not configured"`
- Catch all exceptions within individual checks — one failing check must not
  prevent others from running
- Log at WARNING level for violations, DEBUG for passing checks
- No LLM calls, no file I/O on the hot path (except index consistency which
  only checks in-memory data, not disk files)

---

### File: `src/probos/runtime.py`

**1. Import SIF** at the top:

```python
from probos.sif import StructuralIntegrityField
```

**2. Add `self.sif` in `__init__`** (after the other service instantiations):

```python
self.sif: StructuralIntegrityField | None = None
```

**3. Instantiate SIF in `start()`** (after all subsystems are started, before
the self-mod pipeline setup — SIF needs to reference already-started services):

```python
self.sif = StructuralIntegrityField(
    trust_network=self.trust_network,
    intent_bus=self.intent_bus,
    hebbian_router=self.hebbian_router,
    spawner=self.spawner,
    pool_manager=self.pool_manager,
)
await self.sif.start()
```

**4. Stop SIF in `stop()`** (before other services stop):

```python
if self.sif:
    await self.sif.stop()
```

---

### File: `tests/test_sif.py` (NEW)

Write tests for each invariant check. Strategy: set up bad state, verify SIF
detects it.

**Required tests:**

1. `test_trust_bounds_nan` — inject a NaN trust score, verify `check_trust_bounds()` fails
2. `test_trust_bounds_out_of_range` — inject a score > 1.0, verify detection
3. `test_trust_bounds_pass` — normal scores, verify passing
4. `test_hebbian_bounds_explosion` — inject weight > 10.0, verify detection
5. `test_hebbian_bounds_nan` — inject NaN weight, verify detection
6. `test_hebbian_bounds_pass` — normal weights, verify passing
7. `test_pool_consistency_orphan` — pool references unregistered agent type, verify detection
8. `test_pool_consistency_pass` — pools match templates, verify passing
9. `test_run_all_checks_health_pct` — mix of pass/fail, verify `health_pct` calculation
10. `test_run_all_checks_all_none` — all subsystems None, verify 100% health (graceful degradation)
11. `test_violations_property` — verify `violations` returns only failed checks
12. `test_config_validity_pass` — valid config, verify check passes

**Test patterns:**
- Use `MagicMock` / `AsyncMock` for subsystem references
- For trust bounds: mock `trust_network.all_scores()` to return dict with bad values
- For Hebbian: mock `hebbian_router._weights` as a dict with bad values
- SIF should be testable without a running runtime

## Constraints

- Do NOT modify any UI files
- Do NOT add LLM calls to SIF checks
- Do NOT modify `trust.py`, `intent.py`, `routing.py`, or other subsystem files — SIF reads them read-only
- SIF must be resilient: a None subsystem or an exception in one check must not prevent other checks from running
- Keep the `_check_loop` interval configurable via constructor parameter
- All checks should complete in < 100ms combined (no disk I/O, no network)
