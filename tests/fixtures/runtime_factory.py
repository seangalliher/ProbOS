"""Shared ProbOSRuntime construction and teardown for tests (AD-1270f P1.1/P1.2).

``make_runtime`` and ``started_runtime`` build a runtime with the boot arguments
the per-file fixtures used: ``data_dir=tmp_path / "data"``, a ``MockLLMClient``
unless one is given, and the default config unless one is given.

``stop_runtime(..., fast_teardown=True)`` removes the two fixed shutdown waits
(AD-435, 1 s; BF-296 Phase A, 2 s) from a runtime's FINAL stop only. Those waits
protect in-flight writes, so every other stop keeps production timing: a stop a
test body runs to observe or exercise (lifecycle, shutdown, persistence,
warm-boot and concurrency tests) and any stop that something follows. BF-598
turns every stop after the first into a no-op, so the fast path also does
nothing for a runtime a test body has already stopped.

A final stop has four shapes, and only these may ask for fast teardown:
(a) a yield fixture, as ``async with started_runtime(..., fast_teardown=True)``
around the yield; (b) a test whose body is wholly inside that ``async with``;
(c) a test that starts its runtime and ends with ``try: ... finally: await
stop_runtime(rt, fast_teardown=True)``; (d) a final top-level ``await
stop_runtime(rt, fast_teardown=True)``.

Fast teardown is opt-in and pinned three ways by
tests/test_ad1270f_shutdown_grace.py: ``FAST_TEARDOWN_OPT_IN_FILES`` lists the
files that ask for it; ``FAST_TEARDOWN_EFFECTIVE_MODULES`` lists the test modules
that receive it through a fixture they define or import, from tests/fixtures/ or
from any other test module (any test module may be a fixture source), or that
inherit one by subclassing a class imported from a module that owns a fast class
fixture; and a final-action guard checks that every request is the last action of
its fixture or test (as the first, outermost context of an ``async with``, since
contexts exit right to left). So no opted-in test body observes what stop() leaves
behind. The one intentional exception is tests/test_ad1270f_shutdown_grace.py,
which reads the persisted shutdown marker after a fast teardown on purpose.
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
# scan of every test file. P1.1 extends it file by file, and only for runtimes
# whose final stop is the last thing a fixture or test does; the final-action
# guard in the same test checks that. The one intentional post-stop observer is
# tests/test_ad1270f_shutdown_grace.py itself.
FAST_TEARDOWN_OPT_IN_FILES: frozenset[str] = frozenset({
    "tests/fixtures/experience_shell.py",
    "tests/test_experience_panels.py",
    "tests/test_ad1270f_shutdown_grace.py",
    "tests/test_runtime.py",
    "tests/test_consensus_integration.py",
    "tests/test_distribution.py",
    "tests/test_dag_proposal.py",
    "tests/test_system_qa.py",
    "tests/test_escalation.py",
    "tests/test_self_mod.py",
    "tests/test_emergent_detector.py",
    "tests/test_semantic_knowledge.py",
    "tests/test_scaling.py",
})

# Test modules that RECEIVE fast teardown through a fixture: they define a
# fast-teardown fixture (a class fixture counts), import one from a fixture
# source, which is tests/fixtures/experience_shell.py (``runtime``, and ``shell``,
# which requests it) or any other test module, or import a class from a module
# that owns a fast class fixture, which a subclass inherits. The same test pins
# this set with an AST scan, so a new recipient fails until it has been reviewed
# and added here. A fixture-only module under tests/fixtures/ is a source, not a
# recipient: FAST_TEARDOWN_OPT_IN_FILES pins it.
FAST_TEARDOWN_EFFECTIVE_MODULES: frozenset[str] = frozenset({
    "tests/test_experience.py",
    "tests/test_experience_commands.py",
    "tests/test_experience_nl_memory.py",
    "tests/test_experience_panels.py",
    "tests/test_runtime.py",
    "tests/test_consensus_integration.py",
    "tests/test_distribution.py",
    "tests/test_dag_proposal.py",
    "tests/test_escalation.py",
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
