"""Release each test's finished pytest-timeout ``Timer`` once the test has run.

pytest-timeout's thread method (the only one on Windows) starts a ``threading.Timer`` per test and
parks its ``cancel`` closure on the test item as ``item.cancel_timeout``. Nothing clears it, and pytest
keeps every item until the session ends, so each finished Timer -- with the two ``Event`` locks it owns --
stays alive for the whole worker. On this interpreter every lock is a kernel Semaphore: a worker gained
exactly two handles per test (measured +2.0 per test over 2,874 tests, 94% of all handle growth).

Import ``pytest_runtest_protocol`` into a conftest (or load this module with ``-p``) to activate it.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, Any, None]:
    yield
    # tryfirst makes this the outermost wrapper, so pytest-timeout has already cancelled the timer by now.
    if getattr(item, "cancel_timeout", None) is not None:
        item.cancel_timeout = None
