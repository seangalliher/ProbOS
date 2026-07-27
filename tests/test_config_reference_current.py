"""The generated config reference must not drift from ``probos.config``.

``docs/development/config-reference.md`` is generated from the Pydantic models
by ``scripts/gen_config_reference.py``. A generated doc that nobody regenerates
is worse than no doc: it looks authoritative and lies. This test is the
forcing function -- add or change a config field without regenerating and the
suite goes red.

Fix a failure with::

    python scripts/gen_config_reference.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "gen_config_reference.py"
_DOC = _REPO_ROOT / "docs" / "development" / "config-reference.md"


def test_the_generator_script_exists() -> None:
    assert _SCRIPT.is_file(), (
        "scripts/gen_config_reference.py is missing; the config reference "
        "cannot be regenerated without it"
    )


def test_the_reference_doc_is_committed() -> None:
    assert _DOC.is_file(), (
        "docs/development/config-reference.md is missing; run "
        "python scripts/gen_config_reference.py"
    )


def test_the_reference_matches_the_models() -> None:
    """The committed doc is byte-identical to a fresh generation.

    Runs the real script in ``--check`` mode in a subprocess so the test
    exercises exactly the command a developer is told to run, rather than a
    reimplementation of it that could itself drift.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    assert result.returncode == 0, (
        "config-reference.md is stale.\n"
        "Regenerate with: python scripts/gen_config_reference.py\n\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_the_doc_is_marked_generated() -> None:
    """A reader who lands here from search must not hand-edit it."""
    text = _DOC.read_text(encoding="utf-8")
    assert "do not edit by hand" in text.lower()
    assert "gen_config_reference.py" in text


def test_the_doc_contains_no_platform_dependent_reprs() -> None:
    """The generated doc must be byte-identical on Windows and Linux.

    ``repr()`` of a ``pathlib.Path`` is ``WindowsPath('data')`` on Windows and
    ``PosixPath('data')`` on Linux. Three such defaults shipped in the first
    version of this doc, which made ``--check`` pass locally and fail in CI --
    red on main for three consecutive commits before it was caught.

    The generator now renders paths as POSIX strings. This guard fails fast if
    any future field reintroduces a platform-dependent value, rather than
    letting it surface as an unexplained CI failure on the other OS.
    """
    text = _DOC.read_text(encoding="utf-8")
    offenders = [
        token for token in ("WindowsPath", "PosixPath", "\\\\Users\\\\", "/home/runner")
        if token in text
    ]
    assert not offenders, (
        f"platform-dependent value(s) in the generated config reference: {offenders}. "
        "Render it platform-independently in scripts/gen_config_reference.py "
        "(see _render_value) rather than committing a doc that can only ever be "
        "current on one operating system."
    )


@pytest.mark.parametrize(
    "section",
    ["agentic_loop", "agentic_tools", "records", "consensus", "memory"],
)
def test_load_bearing_sections_are_documented(section: str) -> None:
    """Guards against a generator regression that silently drops sections.

    These five are chosen because each governs behaviour an operator is likely
    to need to change: the loop mechanics, the Sigma commons read/write verbs,
    the records store itself, consensus gating, and memory.
    """
    text = _DOC.read_text(encoding="utf-8")
    assert f"## `{section}`" in text, f"the {section} section vanished from the reference"


def test_the_unbounded_tool_result_default_is_called_out() -> None:
    """``tool_result_max_chars`` ships at 0 = unbounded, which is real exposure.

    The reference is the only place an operator will discover that, so the
    warning is asserted rather than left to survive by good intentions.
    """
    text = _DOC.read_text(encoding="utf-8")
    assert "tool_result_max_chars" in text
    assert "unbounded" in text.lower()
