"""AD-697: Commercial overlay extension-point registry.

Pure OSS plumbing. Allows out-of-tree packages (most importantly any
private a third-party overlay) to plug into well-defined runtime
seams without the OSS tree importing or knowing about them.

Design:
    * Hooks are registered by *name*, never by class. Multiple packages
      may register against the same name; later registrations append.
    * Discovery uses ``importlib.metadata.entry_points(group="probos.extensions")``.
      Each entry point is a zero-arg callable that calls ``register_finalize_hook``
      from this module to install its hooks.
    * Hook execution is opt-in per call site — ``startup/finalize.py``
      invokes ``run_finalize_hooks(runtime, config)`` exactly once at the
      end of its existing wiring.
    * ``is_commercial_loaded()`` is a lightweight predicate the OSS code
      may consult for UI gating ("show upgrade prompt") without importing
      any commercial symbol.

Failure mode: a broken or absent overlay must NEVER prevent the OSS
runtime from booting. All discovery + invocation paths are wrapped with
log-and-degrade.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import os
from typing import Any, Awaitable, Callable, Union

logger = logging.getLogger(__name__)

# Two hook flavors. Sync hooks may return None; async hooks return a coroutine.
SyncFinalizeHook = Callable[[Any, Any], None]
AsyncFinalizeHook = Callable[[Any, Any], Awaitable[None]]
FinalizeHook = Union[SyncFinalizeHook, AsyncFinalizeHook]

ENTRY_POINT_GROUP = "probos.extensions"

_FINALIZE_HOOKS: list[tuple[str, FinalizeHook]] = []
_PROVIDERS: set[str] = set()
_DISCOVERED = False

# AD-698: pre-intent authorization hooks. Each hook receives the
# IntentMessage and returns either True (allow) or False (deny). Hooks
# raising exceptions are treated as deny-with-warning. Multiple hooks
# may be registered; ALL must allow for the broadcast to proceed.
PreIntentAuthHook = Callable[[Any], bool]
_PRE_INTENT_AUTH_HOOKS: list[tuple[str, PreIntentAuthHook]] = []


def register_finalize_hook(
    name: str,
    hook: FinalizeHook,
    *,
    provider: str = "",
) -> None:
    """Register a hook invoked once during runtime finalize.

    Args:
        name: Public seam id (e.g. ``"rbac"``, ``"sso"``,
            ``"admin_dashboard"``). Multiple registrations against the
            same name are allowed and run in registration order.
        hook: Either a sync ``(runtime, config) -> None`` callable or an
            async ``(runtime, config) -> Awaitable[None]`` coroutine fn.
        provider: Typically the overlay package name (any string the
            overlay chooses). Recorded for ``loaded_providers()``
            and ``is_commercial_loaded()``.
    """
    if not name:
        raise ValueError("AD-697: extension hook name must be non-empty")
    _FINALIZE_HOOKS.append((name, hook))
    if provider:
        _PROVIDERS.add(provider)


def discover_extensions() -> None:
    """Iterate entry points and load each. Idempotent.

    Each entry point in the ``probos.extensions`` group must resolve to a
    zero-argument callable. Calling it should perform whatever
    ``register_finalize_hook`` calls the package wants.

    Failures (import errors, raised exceptions inside the loaded
    callable) are logged and swallowed.

    **Operator bypass**: setting ``PROBOS_DISABLE_OVERLAY=1`` (or any
    truthy value other than ``0`` / ``false`` / empty string) skips
    discovery entirely. The overlay package can remain installed in
    the venv; nothing in it loads. Useful for running ProbOS in
    pure-OSS mode without uninstalling the commercial package.
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True
    bypass = os.environ.get("PROBOS_DISABLE_OVERLAY", "").strip().lower()
    if bypass and bypass not in {"0", "false", "no"}:
        logger.info(
            "AD-697: PROBOS_DISABLE_OVERLAY=%s set; skipping overlay discovery (OSS-only mode)",
            bypass,
        )
        return
    eps: Any
    try:
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Older importlib.metadata API (Python < 3.10 select-by-group).
        eps = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:
        logger.warning(
            "AD-697: entry_points() lookup failed; no overlay extensions loaded",
            exc_info=True,
        )
        return
    for ep in eps:
        try:
            fn = ep.load()
        except Exception:
            logger.warning(
                "AD-697: extension entry point '%s' failed to import; "
                "continuing without it",
                getattr(ep, "name", "?"),
                exc_info=True,
            )
            continue
        try:
            fn()
            logger.info(
                "AD-697: loaded extension entry point '%s'", getattr(ep, "name", "?")
            )
        except Exception:
            logger.warning(
                "AD-697: extension entry point '%s' raised during register call; "
                "any partial registrations remain",
                getattr(ep, "name", "?"),
                exc_info=True,
            )


async def run_finalize_hooks(runtime: Any, config: Any) -> None:
    """Invoke every registered finalize hook in registration order.

    Sync and async hooks both supported. Each hook is wrapped in
    log-and-degrade: a raising hook does not abort subsequent hooks or
    the OSS finalize phase.
    """
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
    """True iff at least one provider has registered hooks.

    Today: any provider counts. Future: a tighter contract (capability
    marker, license check) can land in a successor AD without breaking
    callers.
    """
    return bool(_PROVIDERS)


def loaded_providers() -> tuple[str, ...]:
    """Snapshot of provider names that registered hooks (sorted)."""
    return tuple(sorted(_PROVIDERS))


def registered_hook_names() -> tuple[str, ...]:
    """Snapshot of distinct hook names currently registered (sorted)."""
    return tuple(sorted({name for name, _ in _FINALIZE_HOOKS}))


def reset_for_tests() -> None:
    """Test-only: clear registry. Never call from production code."""
    global _DISCOVERED
    _FINALIZE_HOOKS.clear()
    _PROVIDERS.clear()
    _PRE_INTENT_AUTH_HOOKS.clear()
    _DISCOVERED = False


# ---------------------------------------------------------------------------
# AD-698 — pre-intent authorization
# ---------------------------------------------------------------------------


def register_pre_intent_authorization_hook(
    name: str,
    hook: PreIntentAuthHook,
    *,
    provider: str = "",
) -> None:
    """Register a pre-broadcast authorization hook (AD-698).

    Hooks receive the ``IntentMessage`` and must return ``True`` to allow
    or ``False`` to deny. Any exception is treated as deny + warning.
    All registered hooks must return ``True`` for the broadcast to
    proceed. Hooks must be fast — they sit on the hot path of every
    dispatch.

    BF-771: a hook MAY carry internal state. A rate limiter counts, and that
    is precisely why the bus evaluates hooks exactly once per intent. What a
    hook must not do is mutate ship state or block. This previously read
    "side-effect free", which contradicted the rate-limiting use case the seam
    exists to serve.
    """
    if not isinstance(name, str) or not name:
        # BF-771: `if not name` accepted any truthy object. The name becomes the
        # denial `reason` shown to the operator and is the only handle for
        # attributing or removing the policy, so an unnameable hook is a policy
        # nobody can audit or turn off.
        raise ValueError(
            "AD-698: pre-intent auth hook name must be a non-empty str, got "
            f"{type(name).__name__}"
        )
    _PRE_INTENT_AUTH_HOOKS.append((name, hook))
    if provider:
        _PROVIDERS.add(provider)


def evaluate_pre_intent_authorization(intent: Any) -> tuple[bool, str]:
    """Evaluate every registered pre-intent auth hook for ``intent``.

    Returns ``(allowed, reason)``. ``reason`` is empty when allowed.
    Hooks raising exceptions are recorded as denials with their hook
    name and exception type in the reason.
    """
    for name, hook in list(_PRE_INTENT_AUTH_HOOKS):
        try:
            allowed = bool(hook(intent))
        except Exception as exc:
            logger.warning(
                "AD-698: pre-intent auth hook '%s' raised %s; denying intent",
                name, type(exc).__name__, exc_info=True,
            )
            return False, f"{name}:{type(exc).__name__}"
        if not allowed:
            return False, name
    return True, ""


def registered_pre_intent_auth_hook_names() -> tuple[str, ...]:
    return tuple(name for name, _ in _PRE_INTENT_AUTH_HOOKS)
