# BF-090: Exception Audit Phase 2 — Silent Swallows & Bare Catches

## Context

Codebase scorecard graded Exception Handling at **C**. BF-075 Phase 1 addressed ~25 swallowed exceptions, but a comprehensive audit (2026-03-31) reveals **71 silent `except Exception: pass` blocks** across 32 files and **42 bare `except Exception:` handlers** (without `as e`) across 24 files where exception information is permanently lost. Zero bare `except:` (no SystemExit/KeyboardInterrupt leaks — that's clean).

The project's Fail Fast principle states: "Builder must justify every `except Exception: pass`. Three tiers: swallow (non-critical), log-and-degrade (visible degradation), propagate (security/data integrity)."

## Problem

113 exception handlers across 46 production files either:
1. **Silently swallow** — `except Exception: pass` with no logging, metrics, or fallback. Failures are completely invisible.
2. **Lose exception info** — `except Exception:` (no `as e`) with handlers that log a message but cannot include the actual exception details.

## Scope

**Production code only** (`src/probos/`). Do NOT modify test files.

## Rules

### Category 1: Silent Swallows (`except Exception: pass`)

For each occurrence, apply ONE of these treatments:

**A. Convert to logged degradation (default):**
```python
# Before:
except Exception:
    pass

# After:
except Exception:
    logger.debug("Context description failed", exc_info=True)
```

**B. Narrow the exception type (for known failure modes):**
```python
# Before (DB migration idempotency):
except Exception:
    pass

# After:
except sqlite3.OperationalError:
    pass  # Column already exists — migration idempotency
```

**C. Keep as-is with justification comment (only for teardown/cleanup/explicit fallback):**
```python
# Teardown — errors expected and harmless:
except Exception:
    pass  # Teardown cleanup — best-effort, errors harmless
```

### Category 2: Bare Catches Without Binding

For every `except Exception:` where the handler does more than `pass` but has no `as e`:

**Add `as e` binding and include in log, OR add `exc_info=True`:**
```python
# Before:
except Exception:
    logger.warning("Failed to load template: %s", name)

# After:
except Exception:
    logger.warning("Failed to load template: %s", name, exc_info=True)
```

## Detailed Inventory

### Category 1 — Silent Swallows (71 instances)

Work through these file by file, worst offenders first.

#### `cognitive/architect.py` — 9 swallows (lines 269, 448, 458, 481, 492, 506, 520, 533, 544)
All in `perceive()` context-gathering. Each try block gathers one layer of codebase context (architecture tree, import graph, slash commands, API routes, agent map, pool groups, roadmap, progress, decisions). Treatment: **A** — `logger.debug("Context layer <name> unavailable", exc_info=True)` for each.

#### `runtime.py` — 5 swallows (lines 1586, 1921, 2239, 2708, 2757)
- 1586: Intent count → **A** (`logger.debug`)
- 1921: Semantic layer index after agent design → **A**
- 2239: Rejection feedback (comment: "Never block on feedback failure") → **A** with `logger.debug`
- 2708: Semantic skill indexing → **A**
- 2757: Semantic QA report indexing → **A**

#### `cognitive/feedback.py` — 5 swallows (lines 100, 118, 141, 249, 287)
All swallow `event_log.log()` failures for feedback recording. Treatment: **A**. Consider extracting a helper `_safe_log_event(event_log, *args)` that wraps with `logger.debug("Event log write failed", exc_info=True)`, then call that helper in all 5 locations to DRY it up.

#### `cognitive/cognitive_agent.py` — 4 swallows (lines 129, 139, 194, 364)
- 129, 139: Crew list building → **A**
- 194: Journal recording of cached decision → **A**
- 364: Journal recording of LLM call (comment: "Non-critical") → **A**

#### `cognitive/self_mod.py` — 4 swallows (lines 166, 198, 289, 313)
All swallow progress callback failures. Treatment: **C** — these are UI progress callbacks where the WebSocket may have disconnected. Add justification comment: `# UI progress callback — client may have disconnected`.

#### `channels/discord_adapter.py` — 4 swallows (lines 174, 179, 190, 195)
All teardown cleanup (`bot.close()`, `loop.close()`, etc.). Treatment: **C** — add comment: `# Teardown cleanup — errors expected and harmless`.

#### `proactive.py` — 4 swallows (lines 306, 636, 668, 944)
- 306: Recent post count tracking → **A**
- 636, 668: `update_last_seen()` → **A**
- 944: Skill exercise recording → **A**

#### `ward_room.py` — 4 swallows (lines 239, 243, 248, 1164)
- 239, 243, 248: `ALTER TABLE ADD COLUMN` migrations → **B** — narrow to `except sqlite3.OperationalError:` with comment `# Column already exists — migration idempotency`
- 1164: Thread title lookup → **A**

#### `acm.py` — 2 swallows (lines 329, 337)
- 329: Skill profile fetch → **A**
- 337: Episode count → **A**

#### `agents/introspect.py` — 2 swallows (lines 189, 224)
Both → **A**

#### `agents/system_qa.py` — 2 swallows (lines 300, 361)
Event log calls for smoke test → **A**

#### `self_mod_manager.py` — 2 swallows (lines 149, 177)
- 149: Semantic layer indexing → **A**
- 177: Feedback recording → **A**

#### `experience/commands/session.py` — 2 swallows (lines 84, 158)
- 84: Loading past episodic memory → **A**
- 158: Storing conversation episode → **A**

#### `cognitive/episodic.py` — 2 swallows (lines 60, 90)
- 60: `self._client.close()` in `stop()` → **C** (teardown)
- 90: Checking existing episode IDs → **A**

#### `knowledge/embeddings.py` — 2 swallows (lines 121, 141)
Both have explicit programmatic fallback to keyword-based approach → **C** with comment: `# Embedding unavailable — falls through to keyword search`

#### `__main__.py` — 2 swallows (lines 817, 910)
- 817: DB query for active task count (comment: "DB may not exist") → **C** — justified, add comment
- 910: Git commit during reset → **C** (best-effort commit)

#### Files with 1 swallow each (16 files):
| File | Line | Treatment |
|------|------|-----------|
| `build_dispatcher.py` | 233 | **A** |
| `agents/http_fetch.py` | 328 | **A** |
| `cognitive/builder.py` | 587 | **A** |
| `agents/utility/productivity_agents.py` | 90 | **C** — explicit LLM fallback |
| `agents/utility/organizer_agents.py` | 262 | **A** |
| `experience/commands/commands_directives.py` | 343 | **C** — explicit fallback |
| `experience/commands/commands_llm.py` | 117 | **C** — teardown |
| `persistent_tasks.py` | 142 | **B** — narrow to `sqlite3.OperationalError` |
| `cognitive/emergent_detector.py` | 338 | **A** |
| `cognitive/dependency_resolver.py` | 223 | **A** |
| `mesh/capability.py` | 127 | **A** |
| `experience/commands/commands_status.py` | 25 | **A** |
| `startup/shutdown.py` | 59 | **C** — shutdown (comment: "don't block shutdown") |
| `cognitive/strategy.py` | 194 | **C** — explicit keyword fallback |
| `cognitive/journal.py` | 82 | **B** — narrow to `sqlite3.OperationalError` |
| `routers/chat.py` | 218 | **A** |

### Category 2 — Bare Catches Without Binding (42 instances)

For ALL of these, add `exc_info=True` to the existing log call, or add `as e` and include `e` in the message. If the handler has no log call at all (just a `return`/`continue`), add `logger.debug("description", exc_info=True)` before the existing handler body.

#### `knowledge/store.py` — 6 bare catches (lines 413, 538, 551, 594, 641, 651)
- 413: Add `exc_info=True` to existing warning
- 538, 551, 594, 641, 651: Add `logger.debug("Git operation failed", exc_info=True)` before the existing `return`

#### `knowledge/records_store.py` — 4 bare catches (lines 279, 354, 316, 382)
- 279, 354: Add `logger.debug("Skipping unreadable file", exc_info=True)` before `continue`
- 316, 382: Add `logger.debug("Git query failed", exc_info=True)` before `return`

#### `agents/introspect.py` — 3 bare catches (lines 141, 199, 547)
Add `logger.debug(...)` with `exc_info=True` before fallback returns

#### `workforce.py` — 3 bare catches (lines 551, 944, 949)
Add `exc_info=True` to existing `logger.warning()` calls

#### `experience/panels.py` — 2 bare catches (lines 677, 740)
Display fallbacks — add `logger.debug(...)` with `exc_info=True`

#### `proactive.py` — 2 bare catches (lines 755, 1018)
Add `logger.debug("Skipping channel", exc_info=True)` before `continue`

#### `cognitive/episodic.py` — 2 bare catches (lines 248, 408)
Add `logger.debug(...)` with `exc_info=True`

#### `cognitive/self_mod.py` — 2 bare catches (lines 137, 210)
Approval callback errors treated as "declined" — add `logger.warning("Approval callback failed, treating as declined", exc_info=True)`

#### `experience/commands/commands_directives.py` — 2 bare catches (lines 65, 87)
Add `logger.debug(...)` with `exc_info=True`

#### Remaining 1 bare catch each (13 files):
| File | Line | Fix |
|------|------|-----|
| `cognitive/dependency_resolver.py` | 132 | Add `logger.warning("Approval callback failed", exc_info=True)` |
| `cognitive/cognitive_agent.py` | 121 | Add `logger.debug(...)` with `exc_info=True` |
| `api.py` | 260 | Add `logger.debug("WS client prune failed", exc_info=True)` |
| `duty_schedule.py` | 78 | Add `exc_info=True` to existing log |
| `cognitive/architect.py` | 321 | Add `exc_info=True` to existing log |
| `experience/renderer.py` | 397 | Add `logger.debug(...)` with `exc_info=True` |
| `experience/commands/commands_plan.py` | 174 | Add `logger.debug(...)` with `exc_info=True` |
| `crew_profile.py` | 330 | Add `logger.debug("Skipping unreadable profile", exc_info=True)` before `continue` |
| `cognitive/copilot_adapter.py` | 219 | Add `exc_info=True` to existing log |
| `routers/build.py` | 344 | Add `logger.debug(...)` with `exc_info=True` |
| `routers/chat.py` | 319 | Add `logger.debug(...)` with `exc_info=True` |
| `routers/design.py` | 153 | Add `logger.debug(...)` with `exc_info=True` |
| `agents/red_team.py` | 393 | Add `logger.debug("Subprocess failed", exc_info=True)` |
| `knowledge/semantic.py` | 297 | Add `logger.debug(...)` with `exc_info=True` |
| `runtime.py` | 1458 | Add `exc_info=True` to existing log |

## DRY Opportunity

In `cognitive/feedback.py`, all 5 silent swallows wrap `event_log.log()` calls. Extract a helper:

```python
async def _safe_log_event(self, event_log, *args, **kwargs) -> None:
    """Best-effort event logging — never blocks feedback processing."""
    try:
        await event_log.log(*args, **kwargs)
    except Exception:
        logger.debug("Event log write failed", exc_info=True)
```

Then replace each bare try/except with a call to `_safe_log_event()`.

## Verification

After all changes:

1. `grep -rn "except Exception:" src/probos/ | grep "pass$"` — should return ONLY lines with justification comments (treatments B and C)
2. `grep -rn "except Exception:" src/probos/ | grep -v "as e" | grep -v "exc_info"` — should return ONLY justified swallows with comments
3. Run targeted tests: `python -m pytest tests/ -x -q --tb=short`
4. Run full suite: `python -m pytest tests/ -q --tb=short` — expect 4243+ passing

## Principles Compliance

- **Fail Fast**: Every handler now either logs (visible degradation) or has inline justification (swallow)
- **SOLID (S)**: DRY helper in feedback.py keeps single responsibility
- **Defense in Depth**: DB migration narrows to `sqlite3.OperationalError` — only catches the expected failure mode
- **Engineering Principles Stack**: No new debt introduced. All changes are additive logging.

## What NOT to Do

- Do NOT change any behavior — only add logging or narrow exception types
- Do NOT add `raise` to any handler (these are all log-and-degrade paths)
- Do NOT modify test files
- Do NOT add new imports beyond `sqlite3` (already imported in the DB modules) and ensuring `logger = logging.getLogger(__name__)` exists (it does in all these files)
- Do NOT refactor the try/except structure — keep the same block boundaries
- Line numbers are approximate — the audit was done on the current HEAD. If lines have shifted slightly due to BF-089/AD-542 changes, find the nearest matching pattern.
