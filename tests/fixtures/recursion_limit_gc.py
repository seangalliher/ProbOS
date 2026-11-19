"""BF-986 (#1754, GATE-F1): no garbage collection inside a test that runs to the recursion limit.

A collection runs the finalisers of everything it frees on the stack of the code that triggered it. In the last few
frames below the recursion limit there is no room for them. An unclosed event loop that an earlier test left in a
reference cycle raised ``RecursionError`` from ``BaseEventLoop.__del__``, pytest's unraisable hook overflowed while
formatting it, and pytest failed whichever test was running with ``Failed to process unraisable exception``.

A test whose passing path overflows the Python stack (it raises ``RecursionError`` through Python frames, on purpose
or in the code it drives) asks for this fixture with ``@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")``.
Each use costs one full collection.

What it does not stop: a finaliser fired by a reference count reaching zero inside the deep frames; an explicit
``gc.collect()`` in the deep frames that finds garbage the test itself made; a test that overflows without asking for
the fixture. A collection another thread triggers runs on that thread's stack, outside this window. An overflow by C
code alone (the ``json`` scanner or encoder) needs no guard on CPython 3.12: the collector runs only at the
interpreter's eval-breaker checks, which a pure-C recursion reaches only after it has unwound.
"""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest

GUARD_FIXTURE = "gc_quiet_at_recursion_limit"


@pytest.fixture
def gc_quiet_at_recursion_limit() -> Iterator[None]:
    """Collect on a healthy stack, run the test with automatic collection off, then restore the collector's state."""
    was_enabled = gc.isenabled()
    gc.collect()  # on a healthy stack: finalise what earlier tests left, an unclosed event loop in a cycle among it
    gc.disable()  # and start no automatic collection while the test runs to the limit
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
        else:
            gc.disable()  # the test may have turned it on
