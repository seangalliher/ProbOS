# BF-075: Exception Audit — Swallowed Exception Policy

## Problem

The codebase has **98 `except Exception: pass` instances** across 28 files. Most are truly silent — no logging of any kind. While many are acceptable (shutdown teardown, schema migration, best-effort telemetry), approximately **15 are hiding real data loss or degraded behavior** that operators can never diagnose.

The worst pattern: every `episodic_memory.store()` call site silently swallows failures, meaning agents can lose all memory of interactions without any log trace.

## Error Handling Policy

This BF establishes a three-tier policy and applies it to the highest-impact cases:

| Policy | When to Apply | Action |
|--------|---------------|--------|
| **Swallow** | Truly non-critical: shutdown cleanup, UI progress, rebuilable indexes, telemetry | `except Exception: pass` (leave as-is) |
| **Log-and-degrade** | System continues but with reduced capability: lost memories, missed learning, degraded routing | `except Exception: logger.debug("...", exc_info=True)` or `logger.warning(...)` for data loss |
| **Propagate** | Caller must know: trust boundary violations, security-critical failures | `raise` or re-raise |

## Scope

This BF upgrades **~25 high-impact swallowed exceptions** from silent to logged. It does NOT refactor any logic — only adds logging to existing `except Exception: pass` blocks.

## Files to Modify

### 1. `src/probos/runtime.py` — 16 upgrades

All changes follow the same pattern: replace `except Exception: pass` with `except Exception: logger.debug("context message", exc_info=True)`.

Use `logger.warning` for data loss scenarios. Use `logger.debug` for degraded-but-recoverable scenarios.

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 447-448 | `_emit_event()` listener invocation | `debug` | `"Event listener failed for %s", event_type` |
| 653-654 | `status()` emergent detector summary | `debug` | `"Emergent detector summary failed"` |
| 1255-1256 | Stasis recovery session load | `warning` | `"Failed to load session record for lifecycle detection"` |
| 1361-1362 | Cold-start Ward Room announcement | `debug` | `"Cold-start announcement failed"` |
| 1870-1871 | Persist proactive cooldowns at shutdown | `warning` | `"Failed to persist proactive cooldowns"` |
| 2368-2369 | Department lookup from pool groups | `debug` | `"Failed to build department lookup"` |
| 2393-2394 | System mode detection | `debug` | `"System mode detection failed"` |
| 2720-2721 | Persist designed agent to KnowledgeStore | `warning` | `"Failed to persist designed agent — may be lost on restart"` |
| 2866-2867 | Persist episode to KnowledgeStore | `warning` | `"Failed to persist episode — episodic memory data loss"` |
| 3113-3114 | Refresh decomposer descriptors after self-mod | `warning` | `"Failed to refresh decomposer descriptors — self-modified agent may not be routable"` |
| 3122-3123 | Persist patched agent to KnowledgeStore | `warning` | `"Failed to persist patched agent — may be lost on restart"` |
| 4848-4849 | Persist skill to KnowledgeStore | `warning` | `"Failed to persist skill — may be lost on restart"` |
| 5135-5136 | Persist QA report to KnowledgeStore | `debug` | `"Failed to persist QA report"` |
| 5239-5240 | Event log after QA error | `debug` | `"Failed to log QA error event"` |

**Pattern for each:**

Before:
```python
except Exception:
    pass
```

After:
```python
except Exception:
    logger.debug("Event listener failed for %s", event_type, exc_info=True)
```

Or for data loss:
```python
except Exception:
    logger.warning("Failed to persist designed agent — may be lost on restart", exc_info=True)
```

### 2. `src/probos/ward_room.py` — 3 upgrades

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 977-978 | Store thread creation episode | `debug` | `"Failed to store thread creation episode"` |
| 1177-1178 | Store reply episode | `debug` | `"Failed to store reply episode"` |
| 1214-1215 | Hebbian social routing update | `debug` | `"Failed to record Hebbian social interaction"` |

### 3. `src/probos/cognitive/cognitive_agent.py` — 2 upgrades

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 828-829 | Fetch episodic memory context for perceive() | `debug` | `"Failed to fetch episodic memory context"` |
| 892-893 | Store episode after agent action | `debug` | `"Failed to store action episode"` |

### 4. `src/probos/proactive.py` — 2 upgrades

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 131-132 | Restore cooldowns from KnowledgeStore | `info` | `"Failed to restore proactive cooldowns — agents may be temporarily over-active"` |
| 209-210 | ACM activation check | `debug` | `"ACM activation check failed for agent"` |

### 5. `src/probos/cognitive/self_mod.py` — 1 upgrade (propagate candidate)

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 362 | Set probationary trust on newly spawned agent | `warning` | `"Failed to set probationary trust for new agent — trust boundary risk"` |

### 6. `src/probos/api.py` — 2 upgrades

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 1756 | Store 1:1 conversation episode via HXI | `debug` | `"Failed to store HXI conversation episode"` |
| 1784 | Load conversation history for HXI | `debug` | `"Failed to load HXI conversation history"` |

### 7. `src/probos/federation/bridge.py` — 1 upgrade

| Line(s) | Context | Level | Message |
|----------|---------|-------|---------|
| 130 | Federation validation function | `warning` | `"Federation message validator failed — message passed without validation"` |

## What NOT to Change

Leave these as `except Exception: pass` (swallow policy):

- **Schema migration** (`ALTER TABLE ADD COLUMN` catches) — 6 locations across ward_room.py, journal.py, persistent_tasks.py
- **Shutdown teardown** — discord_adapter.py (4 locations), all `stop()` methods
- **UI progress callbacks** — self_mod.py (4 locations)
- **Telemetry/journal recording** — cognitive_agent.py lines 193, 361 ("Non-critical — never block agent cognition")
- **Semantic indexing** — runtime.py lines 2732, 3134, 4858 (rebuildable indexes)
- **Feedback recording** — feedback.py (5 locations, learning telemetry)
- **Architect context enrichment** — architect.py (9 locations, reduced context is acceptable)
- **Embedding fallbacks** — embeddings.py (2 locations, graceful degradation by design)
- **File read in build_dispatcher** — (binary files expected to fail)
- **Status display minor fields** — runtime.py line 2400 (intent count)

## Tests

No new test file needed. The changes are **logging-only** — no behavior changes. Existing tests validate the same code paths. However, verify:

1. Run the full test suite to confirm no regressions
2. Spot-check that `logger` is already imported in each modified file (it should be — all files use `logger = logging.getLogger(__name__)`)

## Implementation Notes

- **Do NOT change any control flow.** Every `except Exception:` block keeps `pass` *in addition to* the new logging call. The exception is still swallowed — we're adding visibility, not changing behavior.
- All messages should include `exc_info=True` so the full traceback appears in debug logs.
- Use `%s` string formatting (not f-strings) in logger calls — this is the standard Python logging pattern that allows lazy formatting.
- **Line numbers are approximate** — they may shift if BF-071 through BF-074 are applied first. Search for the surrounding code context (the try block content) rather than relying on exact line numbers.
- The `logger` variable is already defined at module level in all affected files. No new imports needed.
- Some of these `except` blocks may have `except Exception:` on the same line as `pass` (i.e., `except Exception: pass`). Expand these to two lines:
  ```python
  except Exception:
      logger.debug("message", exc_info=True)
  ```

## Acceptance Criteria

- [ ] ~25 high-impact swallowed exceptions now log at appropriate levels
- [ ] All `logger.warning` calls are for data loss scenarios (agent persistence, episode storage, trust boundaries)
- [ ] All `logger.debug` calls are for degraded-but-recoverable scenarios
- [ ] No control flow changes — all exceptions still swallowed
- [ ] Full test suite passes with no regressions
- [ ] Error handling policy documented in code review file for future reference
