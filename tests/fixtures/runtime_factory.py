"""Shared ProbOSRuntime construction and teardown for tests (AD-1270f P1.1/P1.2).

``make_runtime`` and ``started_runtime`` build a runtime with the boot arguments
the per-file fixtures used: ``data_dir=tmp_path / "data"``, a ``MockLLMClient``
unless one is given, and the default config unless one is given.

``stop_runtime(..., fast_teardown=True)`` removes the two fixed shutdown waits
(AD-435, 1 s; BF-296 Phase A, 2 s) from the TEARDOWN stop only. Those waits
protect in-flight writes, so a stop that a test body runs keeps production
timing: BF-598 turns every stop after the first into a no-op, so the fast path
also does nothing for a runtime a test body has already stopped.

Fast teardown is opt-in and pinned twice by tests/test_ad1270f_shutdown_grace.py:
``FAST_TEARDOWN_OPT_IN_FILES`` lists the files that ask for it, and
``FAST_TEARDOWN_EFFECTIVE_MODULES`` lists the test modules that receive it
through a shared fixture. What stop() leaves behind is not observed by any
opted-in test body; the guards pin that set. The one intentional exception is
tests/test_ad1270f_shutdown_grace.py, which reads the persisted shutdown marker
after a fast teardown on purpose.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType

from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime

# Read-only so a test cannot widen the fast path by mutating the mapping.
FAST_TEARDOWN_OVERRIDES: Mapping[str, float] = MappingProxyType({
    "shutdown_write_grace_s": 0.0,
    "shutdown_dispatch_grace_s": 0.0,
})

# Files that ask for fast teardown: they contain a ``fast_teardown`` keyword that
# is not False. tests/test_ad1270f_shutdown_grace.py pins this set against an AST
# scan of every test file. P1.1 extends it file by file, and only for files whose
# test bodies do not observe what shutdown leaves behind. The one intentional
# observer is tests/test_ad1270f_shutdown_grace.py itself.
FAST_TEARDOWN_OPT_IN_FILES: frozenset[str] = frozenset({
    "tests/fixtures/experience_shell.py",
    "tests/test_experience_panels.py",
    "tests/test_ad1270f_shutdown_grace.py",
})

# Test modules that RECEIVE fast teardown through a shared fixture, with no
# keyword of their own: they import a fast-teardown fixture from
# tests/fixtures/experience_shell.py (``runtime``, and ``shell``, which requests
# it) or define one. The same test pins this set with an AST scan, so a new
# importer fails until it has been reviewed and added here. The fixture module
# itself is the source and is pinned by FAST_TEARDOWN_OPT_IN_FILES.
FAST_TEARDOWN_EFFECTIVE_MODULES: frozenset[str] = frozenset({
    "tests/test_experience.py",
    "tests/test_experience_commands.py",
    "tests/test_experience_nl_memory.py",
    "tests/test_experience_panels.py",
})


def make_runtime(
    tmp_path: Path,
    *,
    llm: BaseLLMClient | None = None,
    config: SystemConfig | None = None,
) -> ProbOSRuntime:
    """Return an unstarted runtime rooted at ``tmp_path / "data"``."""
    return ProbOSRuntime(
        config=config,
        data_dir=tmp_path / "data",
        llm_client=llm or MockLLMClient(),
    )


async def stop_runtime(
    runtime: ProbOSRuntime, *, fast_teardown: bool = False,
) -> None:
    """Stop ``runtime``; with ``fast_teardown`` also skip both fixed grace waits.

    The fast path applies only when no stop has run yet and ``runtime.config``
    is a ``SystemConfig``. It rebinds ``runtime.config`` to a private copy, so
    the caller's config object is never mutated. Every other case stops with
    production timing.
    """
    config = runtime.config
    if (
        fast_teardown
        and getattr(runtime, "_shutdown_started", False) is False
        and isinstance(config, SystemConfig)
    ):
        runtime.config = config.model_copy(update={
            "memory": config.memory.model_copy(update=dict(FAST_TEARDOWN_OVERRIDES)),
        })
    await runtime.stop()


@asynccontextmanager
async def started_runtime(
    tmp_path: Path,
    *,
    llm: BaseLLMClient | None = None,
    config: SystemConfig | None = None,
    fast_teardown: bool = False,
) -> AsyncIterator[ProbOSRuntime]:
    """Start a runtime, yield it, then ``stop_runtime`` it in ``finally``."""
    runtime = make_runtime(tmp_path, llm=llm, config=config)
    await runtime.start()
    try:
        yield runtime
    finally:
        await stop_runtime(runtime, fast_teardown=fast_teardown)
