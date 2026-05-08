# AD-697 v1 — Commercial Overlay Extension Point Registry

**Issue:** (file as new GH issue when ready)
**Type:** Architecture Decision (foundation — pure OSS plumbing)
**Depends on:** none
**Wave:** 111

## Goal

Make it possible to install the (separate, private) `an a third-party overlay` package alongside this OSS repo and have the runtime light up enterprise features automatically — and to flip them off again by uninstalling the package. **No commercial code in this repo.** Only the seam.

The user's flip-the-switch UX target is:

```pwsh
# OSS only
.venv\Scripts\pip uninstall an a third-party overlay -y
# OSS + Commercial overlay
.venv\Scripts\pip install -e ..\an a third-party overlay
```

Same workspace, same data dir, same `config/system.yaml`. The runtime detects the overlay at startup and registers any extension hooks it provides.

## Scope (foundation only)

Ship the **registry, discovery, and one demonstration hook**. Do **not** add any actual commercial-feature seams beyond the demo (RBAC/SSO/admin-dashboard ADs are separate).

## Deliverables

### D1. New module `src/probos/extensions.py`

```python
"""AD-697: Commercial overlay extension-point registry.

Pure OSS plumbing. Allows out-of-tree packages (most importantly
``an a third-party overlay``) to plug into well-defined runtime seams without
the OSS tree importing or knowing about them.

Design:
    * Hooks are registered by *name*, never by class. Multiple packages
      may register against the same name; later registrations append.
    * Discovery uses ``importlib.metadata.entry_points(group="probos.extensions")``.
      Each entry point is a zero-arg callable that calls ``register(...)``
      from this module to install its hooks.
    * Hook execution is opt-in per call site — finalize.py invokes
      ``run_finalize_hooks(runtime, config)`` exactly once at the end of
      its existing wiring.
    * ``is_commercial_loaded()`` is a lightweight predicate the OSS code
      may consult for UI gating ("show upgrade prompt") without importing
      any commercial symbol.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any, Awaitable, Callable, TypeAlias

logger = logging.getLogger(__name__)

# Two hook flavors.
SyncFinalizeHook: TypeAlias = Callable[[Any, Any], None]   # (runtime, config) -> None
AsyncFinalizeHook: TypeAlias = Callable[[Any, Any], Awaitable[None]]

_FINALIZE_HOOKS: list[tuple[str, SyncFinalizeHook | AsyncFinalizeHook]] = []
_PROVIDERS: set[str] = set()
_DISCOVERED = False


def register_finalize_hook(
    name: str,
    hook: SyncFinalizeHook | AsyncFinalizeHook,
    *,
    provider: str = "",
) -> None:
    """Register a hook invoked once during runtime finalize.

    ``name`` is the public seam id (e.g. ``"rbac"``, ``"sso"``,
    ``"admin_dashboard"``). Multiple registrations are allowed and run
    in registration order.

    ``provider`` (typically the overlay package name) is recorded so
    ``is_commercial_loaded()`` and HXI surfaces can show what's active.
    """
    _FINALIZE_HOOKS.append((name, hook))
    if provider:
        _PROVIDERS.add(provider)


def discover_extensions() -> None:
    """Idempotent. Iterate ``probos.extensions`` entry points and call them.

    Each entry point is expected to be a zero-arg callable that performs
    its own ``register_finalize_hook`` calls. Failures are logged and
    swallowed — a broken overlay must not prevent the OSS runtime from
    starting.
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True
    try:
        eps = importlib.metadata.entry_points(group="probos.extensions")
    except TypeError:
        # Older importlib.metadata API
        eps = importlib.metadata.entry_points().get("probos.extensions", [])  # type: ignore[attr-defined]
    for ep in eps:
        try:
            fn = ep.load()
            fn()
            logger.info("AD-697: loaded extension entry point '%s'", ep.name)
        except Exception:
            logger.warning(
                "AD-697: extension entry point '%s' failed to load; "
                "continuing without it", ep.name, exc_info=True,
            )


async def run_finalize_hooks(runtime: Any, config: Any) -> None:
    """Invoke every registered finalize hook. Sync or async accepted."""
    import asyncio
    for name, hook in list(_FINALIZE_HOOKS):
        try:
            result = hook(runtime, config)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning(
                "AD-697: finalize hook '%s' raised; degrading", name, exc_info=True,
            )


def is_commercial_loaded() -> bool:
    """True iff at least one provider registered itself.

    Today: any provider counts. Future: a tighter contract (a marker
    capability, license check, etc.) can land in a successor AD without
    breaking callers.
    """
    return bool(_PROVIDERS)


def loaded_providers() -> tuple[str, ...]:
    """Snapshot of provider names that registered hooks. Order undefined."""
    return tuple(sorted(_PROVIDERS))


def reset_for_tests() -> None:
    """Test-only: clear registry. Never call from production code."""
    _FINALIZE_HOOKS.clear()
    _PROVIDERS.clear()
    global _DISCOVERED
    _DISCOVERED = False
```

### D2. `pyproject.toml`

Declare the entry-point group exists. The OSS package itself does NOT register any entry points — it just defines the group. Add to `[project]` or `[project.entry-points]` section:

```toml
[project.entry-points."probos.extensions"]
# Intentionally empty. Reserved for the an a third-party overlay overlay
# and any future third-party extensions to register against.
```

(If pyproject doesn't permit declaring an empty group, add a single self-referential no-op entry that points to a function in `probos.extensions` that does nothing. Builder must verify.)

### D3. Wire into startup

In `src/probos/startup/finalize.py`, after the existing `_wire_*` calls succeed (or as the very last block), call:

```python
# AD-697: discover and run any installed overlay extensions (e.g. an a third-party overlay)
try:
    from probos.extensions import discover_extensions, run_finalize_hooks
    discover_extensions()
    await run_finalize_hooks(runtime, config)
except Exception:
    logger.warning("AD-697: extension finalize phase failed; continuing OSS-only", exc_info=True)
```

### D4. Runtime predicate for UI / API consumption

Expose a tiny accessor on `runtime`:

```python
# in runtime.py, near other public properties
@property
def commercial_overlay_loaded(self) -> bool:
    """AD-697: True iff a commercial overlay registered any hooks."""
    from probos.extensions import is_commercial_loaded
    return is_commercial_loaded()

@property
def loaded_extension_providers(self) -> tuple[str, ...]:
    from probos.extensions import loaded_providers
    return loaded_providers()
```

### D5. Optional `/api/system/extensions` endpoint

Read-only. Returns `{ "commercial_loaded": bool, "providers": [str, ...] }`. The HXI can use this to gate upgrade prompts without importing any commercial symbol. Add to whichever `routers/` module owns system meta (likely `routers/system.py`).

### D6. Tests — `tests/test_ad697_extensions.py`

Minimum 7:
1. `test_register_finalize_hook_records_name_and_provider`
2. `test_run_finalize_hooks_invokes_sync_and_async`
3. `test_failing_hook_is_logged_and_does_not_propagate`
4. `test_is_commercial_loaded_false_by_default`
5. `test_is_commercial_loaded_true_after_registration`
6. `test_discover_extensions_is_idempotent` (call twice, no double-load)
7. `test_discover_extensions_swallows_broken_entry_point` (use monkeypatch to register an entry point whose `.load()` raises)
8. `test_runtime_commercial_overlay_loaded_property` (construct runtime stub, assert property reflects registry state)

Use `reset_for_tests()` in test setup/teardown to keep tests isolated.

## Hard constraints (do NOT do)

- Do **not** add any actual RBAC/SSO/admin/license logic — that's commercial-only and lives in the private repo.
- Do **not** put commercial business model details in code comments or AD text. The AD itself stays pure OSS plumbing.
- Do **not** require a commercial overlay to be installed for OSS to function.
- Do **not** wire HXI upgrade prompts in this AD — that's a follow-up.
- Do **not** read license files, contact a license server, or anything else network-touching.
- Do **not** break existing finalize.py behavior — the new call is a final additive block.

## Acceptance criteria

- All new code passes lint + has full type annotations on public methods.
- 7+ tests pass.
- Existing test suite passes unchanged (no regressions).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- Manual smoke: with no overlay installed, `runtime.commercial_overlay_loaded` is `False`. Drop a fake entry point (or use the test fixture) to register a no-op hook → `True`.

## Forward markers

- **AD-697-1**: HXI surface — show "Commercial overlay: <providers>" badge in TopNav when `commercial_overlay_loaded`.
- **AD-698**: First real commercial extension point (likely RBAC `pre_intent_authorization` hook) — registered through this registry.
- The commercial repo will ship an `__init__.py` with one entry point that calls `register_finalize_hook("rbac", ..., provider="an a third-party overlay")` on import.

