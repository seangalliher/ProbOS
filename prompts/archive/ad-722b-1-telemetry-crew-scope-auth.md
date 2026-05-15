# AD-722b-1 — Crew-scope auth on avatar-telemetry surfaces (HTTP + WS)

**Wave:** 161
**Closes:** #598
**Status:** **CONDITIONAL — surface scope to Architect before building.** See "Scope flag" below.
**Dependencies:** AD-722b (HTTP snapshot), AD-722b-3 (WS diff push), AD-722b-4 (WS fleet stream).
**Estimated tests:** +8 pytest, 0 vitest.
**Scope tag:** Server-only. Pure internal substrate addition. No new pip deps (uses `fastapi` + stdlib `hmac` for token compare). Apache 2.0.

---

## ⚠️ Scope flag — read FIRST

The issue body says:

> Currently both `GET /api/agent/{id}/avatar-telemetry` and the new `WS /api/agent/{id}/avatar-telemetry-stream` are gated only by `_avatars_feature_check` + `avatar_telemetry.enabled`. **There is no per-crew/per-Captain authentication**; any client that can reach the API has full read access.

The Wave 161 task description says "the same auth used elsewhere in routers/agents.py (likely existing crew-scope middleware/dependency)." **Verification result: NO such dependency exists anywhere in `src/probos/routers/`.** Every endpoint in `routers/agents.py`, `routers/acm.py`, `routers/assignments.py`, etc. uses bare `Depends(get_runtime)`.

The only auth-adjacent string in the entire `src/probos/` tree is `"captain_auth_required"` in `conn.py:57` — a connection-state status enum, not a FastAPI dependency.

**Implication:** this AD is not a migration. It is the **substrate** for crew-scope auth. The dep it lands becomes the pattern every future Wave will mirror.

### Two paths forward — pick before building

**Path A (recommended): land minimal auth substrate, apply to telemetry only.**
- Build a single FastAPI dependency `require_crew_scope` in a new module `src/probos/routers/auth.py`.
- v1 contract: reads bearer token from `Authorization: Bearer <token>` header (HTTP) or `?token=...` query param (WS — WebSocket headers are awkward for browser clients).
- Token compare uses `hmac.compare_digest` against a single shared secret from `AuthConfig.crew_scope_token: str = ""`. Empty token = auth DISABLED (default-OFF for backward compat).
- Apply ONLY to the 3 avatar-telemetry endpoints in this AD.
- Single-Captain v1 — no per-user/per-crew distinction yet. Forward marker covers multi-Captain.

**Path B: split into 1a (HTTP only) + 1b (WS).** WS auth in FastAPI has surface-area gotchas (no `Depends`-style sub-protocol for `WebSocket` handshake; the standard pattern is a manual check inside the endpoint function). If reviewer thinks WS+HTTP in one AD is too wide, recommend the split.

**This prompt is drafted for Path A.** If Builder agrees with the scope, proceed. If Builder hits the WS handshake awkwardness early, the fallback is to ship the HTTP path as AD-722b-1, file the WS path as AD-722b-1a, and surface to Architect.

---

## Solution overview (Path A)

1. New module `src/probos/routers/auth.py` with:
   - `class AuthConfig(BaseModel)` — Pydantic; field `crew_scope_token: str = ""`.
   - `require_crew_scope(authorization: str | None = Header(default=None), runtime: Any = Depends(get_runtime)) -> None` — raises HTTP 401 when configured token is non-empty AND header doesn't match. When configured token is empty, allows through (auth disabled).
   - `verify_ws_token(websocket: WebSocket, runtime: Any) -> bool` — called manually inside WS handlers. Reads `?token=` query param; returns True when ok, calls `websocket.close(code=1008, reason="unauthorized")` and returns False otherwise.
2. New `AuthConfig` field on `Config` Pydantic root (or nested under existing config if there's an obvious home — verify the config shape first).
3. Apply `require_crew_scope` Depends to:
   - `GET /api/agent/{agent_id}/avatar-telemetry` (line 610 in `routers/agents.py`).
   - `GET /api/agent/{agent_id}/avatar-telemetry/history` (line 635).
   - `WS /api/agent/{agent_id}/avatar-telemetry-stream` (line 670 — uses `verify_ws_token` manually since WS endpoints can't use `Depends` for handshake-time auth in FastAPI's pre-accept phase).
   - `WS /api/agent/avatar-telemetry/stream` (the fleet endpoint shipped Wave 160 — verify the exact path; use `grep` against `routers/agents.py`).
4. **Default token is empty string** — auth is OFF by default. Operators opt in by setting `auth.crew_scope_token` in `config/system.yaml`. This matches AD-721d / AD-722 feature-gate convention (default-OFF, breaking change risk = zero).

---

## Section 1 — New module `src/probos/routers/auth.py`

```python
"""AD-722b-1: minimal crew-scope auth dependency for telemetry surfaces.

v1 scope (Wave 161):
- Single shared secret (Pydantic ``AuthConfig.crew_scope_token``).
- HTTP: ``Authorization: Bearer <token>`` header via FastAPI ``Depends``.
- WebSocket: ``?token=<token>`` query param via ``verify_ws_token``.
- Empty configured token = auth disabled (default-OFF).
- Constant-time compare via ``hmac.compare_digest``.

Out of scope (forward markers AD-722b-1a / AD-722b-1b / AD-722b-1c):
- Multi-Captain / per-crew tokens.
- Token rotation / TTL.
- Federation-bridge JWT verification (AD-480 territory).
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, WebSocket

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)


def _configured_token(runtime: Any) -> str:
    """Pull ``auth.crew_scope_token`` from runtime config; empty when unset."""
    cfg = getattr(runtime, "config", None)
    if cfg is None:
        return ""
    auth_cfg = getattr(cfg, "auth", None)
    if auth_cfg is None:
        return ""
    return str(getattr(auth_cfg, "crew_scope_token", "") or "")


async def require_crew_scope(
    authorization: str | None = Header(default=None),
    runtime: Any = Depends(get_runtime),
) -> None:
    """FastAPI dependency: enforce ``Authorization: Bearer <token>`` when configured.

    When ``auth.crew_scope_token`` is empty, this dependency is a pass-through —
    backward-compatible with single-operator HXI installs.

    When configured, missing/malformed/wrong tokens raise HTTP 401.
    """
    expected = _configured_token(runtime)
    if not expected:
        return  # auth disabled
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_or_malformed_authorization")
    presented = authorization[len("Bearer "):].strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid_token")


async def verify_ws_token(websocket: WebSocket, runtime: Any) -> bool:
    """Verify ``?token=`` query param on a WebSocket before ``accept()``.

    On failure, closes with code 1008 and returns False; caller must
    return immediately. On success (or auth-disabled), returns True
    without modifying the WebSocket state.
    """
    expected = _configured_token(runtime)
    if not expected:
        return True
    presented = websocket.query_params.get("token", "") or ""
    if not presented or not hmac.compare_digest(presented, expected):
        # Best-effort close; pre-accept WS may not support all close codes
        # uniformly across Starlette versions, hence the try/except.
        try:
            await websocket.close(code=1008, reason="unauthorized")
        except Exception:
            logger.debug("AD-722b-1: ws close failed during unauthorized rejection", exc_info=True)
        return False
    return True
```

---

## Section 2 — Config field (`src/probos/config.py`)

Add a new Pydantic model and wire it into `SystemConfig` (the root config class in `config.py` — verified at line 3551 as `class SystemConfig(BaseModel)`). Add `auth: AuthConfig = Field(default_factory=AuthConfig)` as a new field on `SystemConfig`.

```python
class AuthConfig(BaseModel):
    """AD-722b-1: minimal crew-scope authentication.

    v1 is single-secret. ``crew_scope_token`` empty (default) disables
    auth entirely — backward-compatible with single-operator HXI installs.
    """

    crew_scope_token: str = Field(
        default="",
        description=(
            "Shared bearer token for crew-scope auth on telemetry surfaces. "
            "Empty string disables auth. Set via config/system.yaml to opt in."
        ),
    )
```

Then on `SystemConfig`:

```python
    auth: AuthConfig = Field(default_factory=AuthConfig)
```

---

## Section 3 — Apply to telemetry endpoints (`src/probos/routers/agents.py`)

### 3.1 — HTTP snapshot endpoint

Find:

```python
@router.get("/{agent_id}/avatar-telemetry")
async def agent_avatar_telemetry(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
```

Replace with:

```python
@router.get("/{agent_id}/avatar-telemetry")
async def agent_avatar_telemetry(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
    _: None = Depends(require_crew_scope),
) -> dict[str, Any]:
```

### 3.2 — HTTP history endpoint

Find the existing `async def agent_avatar_telemetry_history(` signature at line ~635 and add the same `_: None = Depends(require_crew_scope)` parameter.

### 3.3 — Per-agent WS endpoint

Find:

```python
@router.websocket("/{agent_id}/avatar-telemetry-stream")
async def agent_avatar_telemetry_stream(
    websocket: WebSocket,
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> None:
```

Insert the verify-token call **before** `await websocket.accept()`:

```python
@router.websocket("/{agent_id}/avatar-telemetry-stream")
async def agent_avatar_telemetry_stream(
    websocket: WebSocket,
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> None:
    # AD-722b-1: crew-scope auth gate. Verifies ?token= query param when
    # auth.crew_scope_token is configured; pass-through when empty.
    if not await verify_ws_token(websocket, runtime):
        return
    # ... existing body (await websocket.accept() etc.) ...
```

### 3.4 — Fleet WS endpoint (Wave 160)

Locate `fleet_avatar_telemetry_stream` at `src/probos/routers/agents.py:944`. Its signature is `async def fleet_avatar_telemetry_stream(websocket: WebSocket) -> None:` — it does NOT take `runtime` via `Depends`. The handler resolves `runtime = websocket.app.state.runtime` at line 945.

Insert the `verify_ws_token` call AFTER `runtime = websocket.app.state.runtime` resolves and BEFORE `await websocket.accept()` (currently at ~line 960). Place the gate immediately before the existing `avatars_disabled` / `telemetry_disabled` / `fleet_stream_disabled` close-checks, so an unauthorized client closes with 1008 `unauthorized` before any config-state is leaked via close-reason strings.

```python
    runtime = websocket.app.state.runtime
    # AD-722b-1: crew-scope auth gate (pre-accept).
    if not await verify_ws_token(websocket, runtime):
        return
    cfg = getattr(runtime, "config", None)
    # ... existing avatars_cfg / telemetry_cfg checks ...
```

### 3.5 — Imports

Add to the imports at the top of `routers/agents.py`:

```python
from probos.routers.auth import require_crew_scope, verify_ws_token
```

---

## Section 4 — Tests `tests/test_ad722b_1_crew_scope_auth.py`

Eight tests (4 HTTP + 4 WS). Use FastAPI's `TestClient` for HTTP, `TestClient` with `websocket_connect` for WS.

### HTTP tests

1. **`test_http_auth_disabled_allows_through`** — `crew_scope_token = ""`; `GET /api/agent/X/avatar-telemetry` returns 200 (or 404 if agent missing — accept anything NOT 401) without an Authorization header.
2. **`test_http_auth_enabled_missing_header_returns_401`** — `crew_scope_token = "secret"`; no header → 401 with detail `"missing_or_malformed_authorization"`.
3. **`test_http_auth_enabled_wrong_token_returns_401`** — `crew_scope_token = "secret"`; `Authorization: Bearer wrong` → 401 detail `"invalid_token"`.
4. **`test_http_auth_enabled_correct_token_allows_through`** — `crew_scope_token = "secret"`; `Authorization: Bearer secret` → status NOT 401.

### WS tests

5. **`test_ws_auth_disabled_allows_connect`** — `crew_scope_token = ""`; connect `/api/agent/X/avatar-telemetry-stream` without `?token=`; connection accepts (verify via `websocket.receive_text()` doesn't immediately get a close frame).
6. **`test_ws_auth_enabled_missing_token_closes_1008`** — `crew_scope_token = "secret"`; connect without `?token=`; receive close frame with code 1008.
7. **`test_ws_auth_enabled_wrong_token_closes_1008`** — `crew_scope_token = "secret"`; connect with `?token=wrong`; close 1008.
8. **`test_ws_auth_enabled_correct_token_accepts`** — `crew_scope_token = "secret"`; connect with `?token=secret`; connection proceeds (no immediate close).

**Test boundary discipline:**
- Each test uses its own `_FakeRuntime` with a fresh `AuthConfig`.
- TestClient is created per-test (no shared state).
- Use `hmac.compare_digest`-safe test tokens (alphanumeric, no special chars).

---

## Standing rules (must comply)

- **BF-274** — Each endpoint modification uses a single `replace_string_in_file`. The 4 endpoint signatures are NOT adjacent in the file (each is dozens of lines from the next), so `multi_replace_string_in_file` would be safe in principle — but stay with single-replace per BF-274 standing rule.
- **BF-280** — N/A.
- **BF-282** — N/A.
- **BF-286** — N/A.
- **AD-731 invariant** — N/A.
- **AD-738b / UI gate** — N/A (no `ui/src/**` files modified).
- **AD-722c-3 forward-marker style** — technical triggers only.
- **No emoji.**
- **`hmac.compare_digest`** — constant-time compare is required for token verification per OWASP. Do NOT use `==`.
- **Default-OFF** — Empty token = auth disabled. Backward compat REQUIRED.
- **Tier-3 propagate** — HTTP 401 raises; WS rejection closes with 1008. Auth failures must be visible, not swallowed.

---

## Hard-stops (escalate before applying)

- If `routers/agents.py` doesn't import `Header` from FastAPI, add the import — but if there's any other dep collision, SURFACE.
- If the WS handshake-time auth pattern (`verify_ws_token` called BEFORE `await websocket.accept()`) doesn't behave the same under Starlette's current version (e.g. `query_params` not populated pre-accept), STOP and surface — may need to accept first, send error message, then close, which is a different UX.
- If applying `_: None = Depends(require_crew_scope)` breaks existing telemetry tests (`tests/test_ad722_*.py`, `tests/test_ad722b_*.py`, `tests/test_ad722b4_*.py`), the existing tests likely don't set `Authorization` headers — with default-OFF, they should still pass. If they DON'T, surface — there's a test-fixture quirk to debug.
- WS handshake auth in FastAPI / Starlette has historically been fragile. If you can't get a clean test passing for `test_ws_auth_enabled_missing_token_closes_1008` after one diagnostic pass, recommend splitting WS into AD-722b-1a per the scope flag above.

---

## Forward markers (file in `docs/development/roadmap.md`)

- **AD-722b-1a** — Per-crew / per-Captain tokens (multi-tenant). Replace single shared secret with a token store (Pydantic `dict[str, str]` mapping captain_id → token, or backed by ProfileStore). **Trigger:** federation cross-mesh telemetry push (AD-722b-5) lands OR more than one Captain operates the same runtime.
- **AD-722b-1b** — Apply `require_crew_scope` to remaining read endpoints on agents/acm/assignments routers (chat history, agent profile, etc.). **Trigger:** AD-722b-1 ships AND any auth-required-endpoint feature request lands.
- **AD-722b-1c** — Federation-bridge JWT verification (AD-480 integration). **Trigger:** AD-480 federation framework adds cross-mesh agent reads.
- **AD-722b-1d** — Token rotation + TTL. **Trigger:** any single deployment runs > 90 days with a static secret OR security scanner flags long-lived shared-secret use.

---

## Acceptance criteria

1. `src/probos/routers/auth.py` exists with `require_crew_scope` and `verify_ws_token` per Section 1.
2. `AuthConfig` Pydantic model exists in `config.py` with `crew_scope_token: str = ""`; root `Config` has `auth: AuthConfig` field.
3. All 4 avatar-telemetry endpoints (2 HTTP + 2 WS) apply the auth dep / verify call.
4. **Default-OFF backward compat** — existing AD-722* tests pass WITHOUT setting auth headers (because the config default is empty string).
5. 8 new pytest tests pass.
6. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- **PROGRESS.md** — Wave 161 in-flight; close #598.
- **DECISIONS.md** — AD-722b-1 entry. Note that this is the SUBSTRATE for future crew-scope auth — first time the codebase has any auth pattern.
- **docs/development/roadmap.md** — forward markers per above.

---

## Verified Against Codebase (2026-05-15)

```
src/probos/routers/agents.py:
  609: @router.get("/{agent_id}/avatar-telemetry")
  610: async def agent_avatar_telemetry(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
  634: @router.get("/{agent_id}/avatar-telemetry/history")
  635: async def agent_avatar_telemetry_history(
  669: @router.websocket("/{agent_id}/avatar-telemetry-stream")
  670: async def agent_avatar_telemetry_stream(
  943: @router.websocket("/avatar-telemetry/stream")
  944: async def fleet_avatar_telemetry_stream(websocket: WebSocket) -> None:
  945:     runtime = websocket.app.state.runtime
  960:     await websocket.accept()

grep ``from probos.routers.deps import get_runtime`` across src/probos/routers/:
  → bills.py:12, avatars.py:16, assignments.py:11, acm.py:11, agents.py:26, clinical.py:34
  Confirms the dep module name is ``deps`` (not the longer-form alternative).

src/probos/config.py:
  3551: class SystemConfig(BaseModel):
  → root config class; AuthConfig field attaches here.

grep ``crew_scope|require_crew|require_captain|HTTPBearer`` across src/probos:
  → no matches. No existing crew-scope auth dep. This AD is substrate.

grep ``Depends\(`` across src/probos/routers/:
  → 20+ matches; every endpoint uses bare ``Depends(get_runtime)`` only.
  Confirms there is no existing auth pattern to mirror.

src/probos/conn.py:
  57: "captain_auth_required",  # ← STATUS string, not a FastAPI dependency.

GH #598 body: "no per-crew/per-Captain authentication; any client that can
              reach the API has full read access to any agents telemetry."
  → confirms gap; this AD lands the substrate.
```
