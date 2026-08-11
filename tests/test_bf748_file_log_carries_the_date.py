"""BF-748: the file log had no date, so forensics across days was ambiguous.

Both handlers shared one formatter with ``datefmt="%H:%M:%S"``. The console is
fine that way -- the operator is watching it live. The file is not: it is a
rotating archive spanning days and five backups, and a bare clock makes every
query ambiguous the moment it crosses midnight.

Measured 2026-08-11 during the BF-747 verification: a query anchored on "10:16"
matched entries from two different boots on two different days and reported a
working fix as still broken. The answer had to be re-derived by line position
instead. Four live-log investigations in two days had the same exposure.
"""

from __future__ import annotations

import logging
import re

import pytest

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  ")
_CLOCK_ONLY = re.compile(r"^\d{2}:\d{2}:\d{2}  ")


def _handlers() -> tuple[logging.Handler, ...]:
    """Set logging up the way the CLI does, then hand back the handlers."""
    from probos.__main__ import _setup_logging

    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    try:
        _setup_logging("INFO", verbose=False)
        return tuple(root.handlers)
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)


def _render(handler: logging.Handler) -> str:
    record = logging.LogRecord(
        name="probos.mesh.intent", level=logging.INFO, pathname=__file__,
        lineno=1, msg="AD-449: MCPBridge wired (1 server(s) preregistered)",
        args=(), exc_info=None,
    )
    assert handler.formatter is not None
    return handler.formatter.format(record)


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    from logging.handlers import RotatingFileHandler

    out: dict[str, str] = {}
    for h in _handlers():
        if isinstance(h, RotatingFileHandler):
            out["file"] = _render(h)
        elif type(h) is logging.StreamHandler:
            out["console"] = _render(h)
    return out


def test_the_file_log_carries_the_date(rendered: dict[str, str]) -> None:
    line = rendered.get("file")
    assert line is not None, "no RotatingFileHandler was attached"
    assert _ISO.match(line), line


def test_the_console_keeps_the_compact_clock(rendered: dict[str, str]) -> None:
    """Not a cosmetic preference: the console is read live, beside a prompt, and
    a date on every line costs eleven columns for information the operator
    already has.
    """
    line = rendered.get("console")
    assert line is not None, "no console StreamHandler was attached"
    assert _CLOCK_ONLY.match(line), line
    assert not _ISO.match(line), line


def test_only_the_timestamp_differs_between_the_two(rendered: dict[str, str]) -> None:
    """A second divergence would mean two formats to read rather than one format
    at two resolutions. Compared by stripping each timestamp rather than against
    a literal, because the field padding is the formatter's business and writing
    it out by hand just tests my ability to count spaces.
    """
    file_rest = _ISO.sub("", rendered["file"])
    console_rest = _CLOCK_ONLY.sub("", rendered["console"])

    assert file_rest == console_rest
    assert file_rest.startswith("INFO")
    assert "probos.mesh.intent" in file_rest
    assert file_rest.endswith("AD-449: MCPBridge wired (1 server(s) preregistered)")


def test_the_date_is_the_only_thing_added(rendered: dict[str, str]) -> None:
    """The file line is the console line with a date in front of it."""
    console_clock = rendered["console"][:8]
    assert rendered["file"].startswith(f"2")          # a year, not a clock
    assert console_clock in rendered["file"][:20]


def test_the_file_timestamp_sorts_lexically(rendered: dict[str, str]) -> None:
    """Y-m-d H:M:S is chosen over any local convention because sorting the text
    sorts the events, which is what a grep-based investigation relies on.
    """
    fmt = logging.Formatter("%(asctime)s", datefmt="%Y-%m-%d %H:%M:%S")
    stamps = []
    for created in (1_754_000_000.0, 1_754_086_400.0, 1_754_172_800.0):
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "m", (), None)
        rec.created = created
        stamps.append(fmt.format(rec))

    assert stamps == sorted(stamps)
