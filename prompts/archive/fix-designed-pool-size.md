# AD-265: Designed Agent Pool Size = 1

## Problem

Self-designed agents spawn in pools of 2 (hardcoded). The IntentBus fans out `broadcast()` to ALL subscribers in a pool. When a designed agent overrides `perceive()` with httpx (the AD-228 web-fetching template), both pool members call the external API simultaneously. This doubles API requests, wastes quota, and triggers rate limits (observed: CoinGecko 429 on first request from a freshly designed Bitcoin price agent).

## Fix

One-line change. Two files.

### File: `src/probos/cognitive/self_mod.py` (line 313)

Change:
```python
await self._create_pool_fn(agent_type, pool_name, 2)
```
to:
```python
await self._create_pool_fn(agent_type, pool_name, 1)
```

### File: `src/probos/runtime.py` (line 2120)

Change the default parameter:
```python
async def _create_designed_pool(self, agent_type: str, pool_name: str, size: int = 2) -> None:
```
to:
```python
async def _create_designed_pool(self, agent_type: str, pool_name: str, size: int = 1) -> None:
```

### File: `tests/test_self_mod.py` (line 601)

Update the mock to match:
```python
async def create_pool_fn(agent_type, pool_name, size=2):
```
to:
```python
async def create_pool_fn(agent_type, pool_name, size=1):
```

## Tests

No new tests needed. The existing test (`test_full_pipeline_end_to_end`) checks `len(mocks["pools"]) == 1` and `mocks["pools"][0][1] == "designed_count_words"` — neither asserts pool size = 2.

Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## PROGRESS.md

Update:
- Status line (line 3) test count if it changed
- Add this section before `## Active Roadmap`:

```
### AD-265: Designed Agent Pool Size = 1

**Problem:** Self-designed agents spawned in pools of 2. The IntentBus fans out to all pool subscribers, so web-fetching agents with `perceive()` httpx overrides made 2 identical HTTP requests per intent — doubling API quota usage and triggering rate limits (observed: CoinGecko 429 on first request from Bitcoin price agent).

| AD | Decision |
|----|----------|
| AD-265 | Designed agent pool default size changed from 2 to 1. The PoolScaler can still scale up later based on demand. One agent per pool eliminates duplicate API calls while preserving all existing scaling infrastructure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/self_mod.py` | `_create_pool_fn(agent_type, pool_name, 2)` → `1` |
| `src/probos/runtime.py` | `_create_designed_pool` default `size` parameter `2` → `1` |
| `tests/test_self_mod.py` | Mock `create_pool_fn` default `size` parameter `2` → `1` |

NNNN/NNNN tests passing (+ 11 skipped). 0 new tests.
```

Replace NNNN with the actual test count.

## Constraints

- Only touch 3 files: `src/probos/cognitive/self_mod.py`, `src/probos/runtime.py`, `tests/test_self_mod.py`
- Also update `PROGRESS.md`
- Do NOT change any other files
- Do NOT add new tests — existing tests cover this
- Do NOT change any other pool sizes (skills pool, bundled pools, etc.)
