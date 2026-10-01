"""Shared fixtures for the split test_experience*.py modules.

Moved verbatim from the original single test_experience.py.
"""

from io import StringIO

import pytest
from rich.console import Console

from probos.cognitive.llm_client import MockLLMClient
from probos.experience.shell import ProbOSShell
from probos.runtime import ProbOSRuntime


@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with MockLLMClient, start it, yield, stop."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


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
