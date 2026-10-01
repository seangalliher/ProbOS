"""Shared fixtures for the split test_experience*.py modules.

Moved verbatim from the original single test_experience.py.

AD-1270f P1.2: the ``runtime`` fixture opts in to fast teardown (see
tests/fixtures/runtime_factory.py), so its teardown stop skips the two fixed
shutdown graces. That opt-in covers every module that imports this ``runtime``
fixture, so none of them may assert on what ``stop()`` leaves behind. A test
that stops the runtime in its own body keeps production timing: the factory's
teardown stop is then a BF-598 no-op.
"""

from io import StringIO

import pytest
from rich.console import Console

from probos.experience.shell import ProbOSShell

from tests.fixtures.runtime_factory import started_runtime


@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with MockLLMClient, start it, yield, stop."""
    async with started_runtime(tmp_path, fast_teardown=True) as rt:
        yield rt


@pytest.fixture
def console():
    """Console that captures output to a StringIO buffer."""
    return Console(file=StringIO(), force_terminal=True, width=120)


@pytest.fixture
async def shell(runtime, console):
    """Shell with captured console output."""
    return ProbOSShell(runtime, console=console)


def get_output(con: Console) -> str:
    """Extract the captured console output."""
    return con.file.getvalue()
