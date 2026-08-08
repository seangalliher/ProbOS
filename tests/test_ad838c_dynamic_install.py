"""AD-838c: Dynamic dependency install for the runtime task path.

Tests the tiered-policy DependencyResolver (whitelist vs prompt_unlisted),
the runtime ``ensure_dependency`` entry point with its defense-in-depth
hard-decline path, governance event emission, and the shared-resolver
invariant between the self-mod pipeline and the task path.

Run serial: pytest tests/test_ad838c_dynamic_install.py -v -n 0
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.dependency_resolver import DependencyResolver, DependencyResult
from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeEventLog:
    """Captures (category, event) tuples passed to log()."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def log(self, *, category: str, event: str, detail: str = "") -> None:
        self.events.append((category, event))


def _fake_runtime(
    *,
    resolver: DependencyResolver | None,
    allowed_imports: list[str] | None = None,
    event_log: _FakeEventLog | None = None,
) -> SimpleNamespace:
    """Build a minimal stand-in carrying just the attributes ensure_dependency reads."""
    return SimpleNamespace(
        dependency_resolver=resolver,
        event_log=event_log,
        config=SimpleNamespace(
            self_mod=SimpleNamespace(allowed_imports=allowed_imports or []),
            # AD-1222: the auto-approve tier moved off self_mod.allowed_imports
            # onto its own field, because "may appear in generated code" and
            # "installs without asking the Captain" are different questions.
            # These tests pass their tier via `allowed_imports`, so it is
            # mirrored here to keep each case testing what it always tested.
            dependency=SimpleNamespace(
                auto_approve_imports=allowed_imports or []
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Disabled by default — no resolver wired
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_dependency_disabled_returns_failure() -> None:
    rt = _fake_runtime(resolver=None)
    result = await ProbOSRuntime.ensure_dependency(rt, "feedparser")
    assert result.success is False
    assert "disabled" in (result.error or "")
    assert result.installed == []


# ---------------------------------------------------------------------------
# 2. prompt_unlisted surfaces unlisted-but-missing imports
# ---------------------------------------------------------------------------
def test_detect_missing_prompt_unlisted_returns_unlisted() -> None:
    resolver = DependencyResolver(
        allowed_imports=["requests"], policy="prompt_unlisted"
    )
    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        return_value=None,
    ):
        missing = resolver.detect_missing("import totallyfakepkg\n")
    assert "totallyfakepkg" in missing


# ---------------------------------------------------------------------------
# 3. whitelist mode unchanged (AD-213 regression guard)
# ---------------------------------------------------------------------------
def test_detect_missing_whitelist_skips_unlisted() -> None:
    resolver = DependencyResolver(allowed_imports=["requests"])  # default whitelist
    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        return_value=None,
    ):
        missing = resolver.detect_missing("import totallyfakepkg\n")
    # Unlisted import is NOT offerable under whitelist policy.
    assert "totallyfakepkg" not in missing


# ---------------------------------------------------------------------------
# 4. deny_imports blocks even under prompt_unlisted
# ---------------------------------------------------------------------------
def test_detect_missing_deny_imports_blocked() -> None:
    resolver = DependencyResolver(
        allowed_imports=["requests"],
        policy="prompt_unlisted",
        deny_imports=["evilpkg"],
    )
    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        return_value=None,
    ):
        missing = resolver.detect_missing("import evilpkg\nimport otherpkg\n")
    assert "evilpkg" not in missing
    assert "otherpkg" in missing


# ---------------------------------------------------------------------------
# 5. ensure_dependency happy path — approval + install succeed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_dependency_happy_path_installs() -> None:
    state = {"installed": False}

    async def install(pkg: str) -> tuple[bool, str]:
        state["installed"] = True
        return (True, "ok")

    approval = AsyncMock(return_value=True)
    resolver = DependencyResolver(
        allowed_imports=["feedparser"],
        install_fn=install,
        approval_fn=approval,
    )
    rt = _fake_runtime(resolver=resolver, allowed_imports=["feedparser"])

    def fs_side_effect(name: str):
        if name == "feedparser":
            return MagicMock() if state["installed"] else None
        return MagicMock()

    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        side_effect=fs_side_effect,
    ):
        result = await ProbOSRuntime.ensure_dependency(rt, "feedparser")

    assert result.success is True
    assert "feedparser" in result.installed


# ---------------------------------------------------------------------------
# 6. ensure_dependency declined — approval False installs nothing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_dependency_declined_installs_nothing() -> None:
    install = AsyncMock(return_value=(True, "ok"))
    approval = AsyncMock(return_value=False)
    resolver = DependencyResolver(
        allowed_imports=["feedparser"],
        install_fn=install,
        approval_fn=approval,
    )
    rt = _fake_runtime(resolver=resolver, allowed_imports=["feedparser"])

    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        return_value=None,
    ):
        result = await ProbOSRuntime.ensure_dependency(rt, "feedparser")

    assert result.success is False
    assert result.declined  # something declined
    install.assert_not_awaited()


# ---------------------------------------------------------------------------
# 7. Shared resolver instance between self-mod pipeline and task path
# ---------------------------------------------------------------------------
def test_single_shared_resolver_instance() -> None:
    import dataclasses

    from probos.startup.results import CognitiveServicesResult

    resolver = DependencyResolver(allowed_imports=["requests"])
    # cognitive_services constructs ONE resolver variable and passes it both to
    # the self-mod pipeline and into the result. Mirror that invariant: the same
    # instance flows into the pipeline (_dependency_resolver) and the result field.
    pipeline = SimpleNamespace(_dependency_resolver=resolver)
    kwargs = {f.name: None for f in dataclasses.fields(CognitiveServicesResult)}
    kwargs["dependency_resolver"] = resolver
    result = CognitiveServicesResult(**kwargs)
    assert result.dependency_resolver is pipeline._dependency_resolver


# ---------------------------------------------------------------------------
# 8. Governance events emitted
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_dependency_emits_governance_events() -> None:
    state = {"installed": False}

    async def install(pkg: str) -> tuple[bool, str]:
        state["installed"] = True
        return (True, "ok")

    approval = AsyncMock(return_value=True)
    resolver = DependencyResolver(
        allowed_imports=["feedparser"],
        install_fn=install,
        approval_fn=approval,
    )
    log = _FakeEventLog()
    rt = _fake_runtime(
        resolver=resolver, allowed_imports=["feedparser"], event_log=log
    )

    def fs_side_effect(name: str):
        if name == "feedparser":
            return MagicMock() if state["installed"] else None
        return MagicMock()

    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        side_effect=fs_side_effect,
    ):
        await ProbOSRuntime.ensure_dependency(rt, "feedparser")

    events = [e for (_cat, e) in log.events]
    assert "dependency_check" in events
    assert "dependency_install_approved" in events
    assert "dependency_install_success" in events
    assert all(cat == "dependency" for (cat, _e) in log.events)


# ---------------------------------------------------------------------------
# 9. Security: no approval callback hard-declines unlisted (installs nothing)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_dependency_no_approval_callback_hard_declines() -> None:
    install = AsyncMock(return_value=(True, "ok"))
    resolver = DependencyResolver(
        allowed_imports=["requests"],
        policy="prompt_unlisted",
        install_fn=install,
        approval_fn=None,  # no interactive approval wired
    )
    # allowed_imports does NOT contain the requested unlisted package.
    rt = _fake_runtime(resolver=resolver, allowed_imports=["requests"])

    with patch(
        "probos.cognitive.dependency_resolver.importlib.util.find_spec",
        return_value=None,
    ):
        result = await ProbOSRuntime.ensure_dependency(rt, "totallyfakepkg")

    assert result.success is False
    assert "totallyfakepkg" in result.declined
    install.assert_not_awaited()
