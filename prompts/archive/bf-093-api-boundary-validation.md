# BF-093: API Boundary Validation

## Context

Codebase scorecard graded API boundary validation at **A-** with gaps. Most API endpoints use Pydantic models (see `api_models.py`), but 4 endpoints accept raw `dict` payloads with no validation. ACM endpoints return `200 OK` with `{"error": ...}` instead of proper `HTTPException` status codes — an anti-pattern no other router uses.

## Problem

Two categories:
1. **Raw `dict` request bodies** — 4 endpoints accept `req: dict` instead of Pydantic models
2. **ACM error anti-pattern** — 3 endpoints return `{"error": str}` with HTTP 200 instead of raising `HTTPException`

## Part 1: New Pydantic Models

Add to `src/probos/api_models.py`, after the Assignment models section:

```python
# ── ACM lifecycle models (BF-093) ────────────────────────────────

class AgentLifecycleRequest(BaseModel):
    """Request body for ACM lifecycle transitions (decommission/suspend/reinstate)."""
    reason: str = ""


# ── Agent cooldown model (BF-093) ────────────────────────────────

class SetCooldownRequest(BaseModel):
    """Request body for per-agent proactive cooldown."""
    cooldown: float = 300.0  # seconds, range 60–1800
```

**Note:** All three ACM endpoints (`decommission`, `suspend`, `reinstate`) share the same shape — just a `reason` string. One model is correct here per DRY. If future endpoints need different fields, they can subclass.

## Part 2: ACM Router — Pydantic Models + Proper HTTP Errors

File: `src/probos/routers/acm.py`

### 2a. Add imports

Add `HTTPException` to the fastapi import:
```python
from fastapi import APIRouter, Depends, HTTPException
```

Add the model import:
```python
from probos.api_models import AgentLifecycleRequest
```

### 2b. Fix `decommission_agent` (line ~48)

**Before:**
```python
async def decommission_agent(agent_id: str, req: dict, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    if not runtime.acm:
        return {"error": "ACM not available"}
    reason = req.get("reason", "Decommissioned by Captain")
    ...
    except ValueError as e:
        return {"error": str(e)}
```

**After:**
```python
async def decommission_agent(agent_id: str, req: AgentLifecycleRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    if not runtime.acm:
        raise HTTPException(status_code=503, detail="ACM not available")
    reason = req.reason or "Decommissioned by Captain"
    ...
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
```

### 2c. Fix `suspend_agent` (line ~64)

Same pattern:
- `req: dict` → `req: AgentLifecycleRequest`
- `return {"error": "ACM not available"}` → `raise HTTPException(status_code=503, detail="ACM not available")`
- `req.get("reason", "Suspended by Captain")` → `req.reason or "Suspended by Captain"`
- `return {"error": str(e)}` → `raise HTTPException(status_code=409, detail=str(e))`

### 2d. Fix `reinstate_agent` (line ~84)

Same pattern:
- `req: dict` → `req: AgentLifecycleRequest`
- `return {"error": "ACM not available"}` → `raise HTTPException(status_code=503, detail="ACM not available")`
- `req.get("reason", "Reinstated by Captain")` → `req.reason or "Reinstated by Captain"`
- `return {"error": str(e)}` → `raise HTTPException(status_code=409, detail=str(e))`

**HTTP status codes used:**
- `503` — ACM service not available (matches every other router's pattern for missing services)
- `409` — Conflict (lifecycle transition not allowed from current state — e.g., decommissioning an already-decommissioned agent). `ValueError` from ACM means the state machine rejected the transition.

## Part 3: Cooldown Endpoint — Pydantic Model + Range Validation

File: `src/probos/routers/agents.py`

### 3a. Add import

```python
from probos.api_models import SetCooldownRequest
```

### 3b. Fix `set_agent_proactive_cooldown` (line ~147)

**Before:**
```python
async def set_agent_proactive_cooldown(agent_id: str, req: dict, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    ...
    cooldown = float(req.get("cooldown", 300))
    if hasattr(runtime, 'proactive_loop') and runtime.proactive_loop:
        runtime.proactive_loop.set_agent_cooldown(agent_id, cooldown)
```

**After:**
```python
async def set_agent_proactive_cooldown(agent_id: str, req: SetCooldownRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    ...
    cooldown = req.cooldown
    if cooldown < 60 or cooldown > 1800:
        raise HTTPException(status_code=400, detail=f"Cooldown must be between 60 and 1800 seconds, got {cooldown}")
    if hasattr(runtime, 'proactive_loop') and runtime.proactive_loop:
        runtime.proactive_loop.set_agent_cooldown(agent_id, cooldown)
```

**Design choice:** Range validation is done in the handler (not as a Pydantic validator) because the docstring says "Range: 60–1800" and a clear `HTTPException(400)` with the exact constraint is better UX than a generic Pydantic validation error. Either approach is acceptable.

## Part 4: Tests

### 4a. ACM endpoint tests

File: `tests/test_acm.py` (extend existing)

Add tests that verify:
1. Each ACM endpoint accepts the new model shape `{"reason": "test"}` and returns the expected response
2. Each ACM endpoint raises `HTTPException(503)` when `runtime.acm` is `None`
3. Each ACM endpoint raises `HTTPException(409)` when `acm.decommission()` / `acm.transition()` raises `ValueError`
4. Each ACM endpoint works with empty body `{}` (reason defaults)

### 4b. Cooldown endpoint tests

File: `tests/test_proactive.py` or a new section in existing agent router tests

Add tests that verify:
1. Valid cooldown `{"cooldown": 300}` is accepted ← already implicitly tested
2. Cooldown below 60 returns `HTTPException(400)`
3. Cooldown above 1800 returns `HTTPException(400)`
4. Default cooldown (empty body → 300.0) is within range and accepted

## Verification

```bash
uv run pytest tests/test_acm.py tests/test_proactive.py -v
```

No raw `dict` request bodies should remain in any router:
```bash
grep -n "req: dict" src/probos/routers/*.py
```
Should return zero matches after this fix.

## Principles Compliance

- **Defense in Depth:** Validate at API boundary (Pydantic) AND handler boundary (range check)
- **Fail Fast:** Proper HTTP status codes instead of silent 200+error
- **DRY:** One model for three identical ACM request shapes
- **SOLID (ISP):** Model has minimal fields — no extra baggage
