# Build Prompt: Self-Mod Registration Rollback (AD-368)

## Context

GPT-5.4 code review found that in the self-mod pipeline, if agent type
registration succeeds (step 4, `self_mod.py:315`) but pool creation fails
(step 5, `self_mod.py:334`), the agent type remains registered in the
spawner and decomposer intent descriptors — but no pool exists to run it.
The system would route intents to this phantom agent type, with all dispatch
attempts failing.

The fix: add rollback of the registration when pool creation fails.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `src/probos/cognitive/self_mod.py`

**Change 1:** Add an `_unregister_fn` parameter to the pipeline, alongside
the existing `_register_fn`. This needs to be set during initialization.

Find where `_register_fn` and `_create_pool_fn` are stored (in `__init__`
or wherever they are assigned). Add `_unregister_fn` with the same pattern:

```python
self._unregister_fn = unregister_fn  # Added for rollback (AD-368)
```

**Change 2:** In the `failed_pool` error handler (around line 335-348), add
rollback of the registration before returning the failure record:

Before:
```python
    except Exception as e:
        logger.warning("Pool creation failed for %s: %s", intent_name, e)
        record = DesignedAgentRecord(
            ...
            status="failed_pool",
            error=f"Pool creation: {e}",
        )
        self._records.append(record)
        return record
```

After:
```python
    except Exception as e:
        logger.warning("Pool creation failed for %s: %s", intent_name, e)
        # Rollback registration to avoid phantom agent type (AD-368)
        if self._unregister_fn:
            try:
                await self._unregister_fn(agent_type)
            except Exception as rollback_err:
                logger.warning("Registration rollback failed for %s: %s",
                               agent_type, rollback_err)
        record = DesignedAgentRecord(
            ...
            status="failed_pool",
            error=f"Pool creation: {e}",
        )
        self._records.append(record)
        return record
```

### File: `src/probos/runtime.py`

**Change 3:** Add an `unregister_agent_type` method to the runtime (near
`register_agent_type` at line 275):

```python
def unregister_agent_type(self, type_name: str) -> None:
    """Unregister an agent class and refresh the decomposer's intent descriptors."""
    self.spawner.unregister_template(type_name)
    if self.decomposer:
        self.decomposer.refresh_descriptors(self._collect_intent_descriptors())
```

**Change 4:** Check if `spawner.unregister_template()` exists. If it doesn't,
add it to the spawner. Look at the `AgentSpawner` class — find
`register_template` and add a corresponding `unregister_template`:

```python
def unregister_template(self, type_name: str) -> None:
    """Remove a registered agent template."""
    self._templates.pop(type_name, None)
```

**Change 5:** Wire `unregister_agent_type` into the self-mod pipeline
initialization. Find where the pipeline is created in `runtime.py` (search
for `SelfModPipeline` or where `_register_fn` is passed). Add
`unregister_fn`:

```python
# Current (approximate):
self.self_mod_pipeline = SelfModPipeline(
    register_fn=...,
    create_pool_fn=...,
    ...
)

# Updated:
self.self_mod_pipeline = SelfModPipeline(
    register_fn=...,
    unregister_fn=self.unregister_agent_type,
    create_pool_fn=...,
    ...
)
```

Adapt to the actual constructor signature — the pipeline may use direct
attribute assignment or kwargs.

---

## Tests

### File: `tests/test_self_mod.py`

Add a test verifying rollback happens on pool creation failure:

```python
@pytest.mark.asyncio
async def test_failed_pool_rolls_back_registration():
    """If pool creation fails, the agent type registration should be rolled back."""
    from unittest.mock import AsyncMock, MagicMock

    register_fn = AsyncMock()
    unregister_fn = AsyncMock()
    create_pool_fn = AsyncMock(side_effect=RuntimeError("Pool creation failed"))

    pipeline = SelfModPipeline(
        llm_client=MagicMock(),
        register_fn=register_fn,
        unregister_fn=unregister_fn,
        create_pool_fn=create_pool_fn,
        set_trust_fn=AsyncMock(),
    )

    # Mock the design/sandbox steps to succeed
    # ... (adapt based on how the pipeline is tested in existing tests)

    # The unregister function should have been called for rollback
    # unregister_fn.assert_called_once()
```

Note: The exact test setup depends on how `SelfModPipeline.__init__` works in
the current codebase. Check existing tests in `test_self_mod.py` for the
pattern — follow whatever setup the existing `failed_pool` test uses and
add an assertion that the unregister function was called.

---

## Constraints

- Modify `src/probos/cognitive/self_mod.py`, `src/probos/runtime.py`, and
  possibly the spawner file (check where `register_template` is defined)
- Follow existing patterns for how functions are passed to the pipeline
- Do NOT change any other pipeline steps — only add rollback to step 5 failure
- The rollback itself must be wrapped in try/except (don't let rollback
  failure mask the original pool creation error)
- Run `pytest tests/test_self_mod.py -x -q` to verify
