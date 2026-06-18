"""AD-1026 — quiet, phased boot output with a ``--verbose`` flag.

Presentation-only coverage for the boot-verbosity helpers in
``probos.__main__``: the console-level resolver, the ``_setup_logging``
console/file handler levels, the collapsed-vs-verbose pool summary (incl.
degraded-pool surfacing), the WARNING+ boot counter, and the ``serve
--verbose``/``-v`` argparse wiring.

Logging assertions inspect REAL handler objects (BF-287 — no MagicMock at the
logging boundary). ``_setup_logging`` mutates the global root logger, so every
test that calls it runs under the ``_logger_state`` fixture which snapshots and
restores the root logger's handlers + level and closes any file handler the
call opened (FD hygiene).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import pytest

import probos.__main__ as m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def _logger_state():
    """Snapshot/restore the root logger's handlers + level around a test.

    ``_setup_logging`` adds console/file/counter handlers to the global root
    logger and pins per-logger levels. Without restoration these leak across
    tests and the file handler accumulates open descriptors. We restore the
    handler list + level and close any file handler the test opened.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        for h in list(root.handlers):
            if h not in saved_handlers and isinstance(h, logging.FileHandler):
                try:
                    h.close()
                except Exception:
                    pass
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def _sample_status(*, degraded: bool = False) -> dict:
    """Minimal ``runtime.status()``-shaped dict for summary rendering."""
    return {
        "total_agents": 20,
        "pools": {
            "filesystem": {
                "name": "filesystem",
                "agent_type": "FileReaderAgent",
                "target_size": 3,
                "current_size": 1 if degraded else 3,
                "agents": [],
            },
            "shell": {
                "name": "shell",
                "agent_type": "ShellCommandAgent",
                "target_size": 2,
                "current_size": 2,
                "agents": [],
            },
        },
        "consensus": {"red_team_agents": 4},
    }


def _console_handlers(
    root: logging.Logger, before: frozenset | set = frozenset()
) -> list[logging.Handler]:
    """Plain console StreamHandlers added since ``before`` (exact type —
    excludes FileHandler, the WARNING counter, and pytest's LogCaptureHandler
    subclass)."""
    return [
        h
        for h in root.handlers
        if h not in before and type(h) is logging.StreamHandler
    ]


def _file_handlers(
    root: logging.Logger, before: frozenset | set = frozenset()
) -> list[logging.Handler]:
    """FileHandlers added since ``before`` (excludes any pre-existing foreign
    file handler such as the pytest null-device capture handler)."""
    return [
        h
        for h in root.handlers
        if h not in before and isinstance(h, logging.FileHandler)
    ]


# ---------------------------------------------------------------------------
# DD-1: _console_log_level mapping
# ---------------------------------------------------------------------------
def test_console_log_level_info_not_verbose_is_warning():
    assert m._console_log_level("INFO", verbose=False) == logging.WARNING


def test_console_log_level_info_verbose_is_info():
    assert m._console_log_level("INFO", verbose=True) == logging.INFO


def test_console_log_level_debug_verbose_is_debug():
    assert m._console_log_level("DEBUG", verbose=True) == logging.DEBUG


def test_console_log_level_unknown_verbose_falls_back_to_info():
    assert m._console_log_level("NOTALEVEL", verbose=True) == logging.INFO


def test_console_log_level_unknown_not_verbose_is_warning():
    # When quiet, the console is WARNING regardless of the (unknown) level.
    assert m._console_log_level("NOTALEVEL", verbose=False) == logging.WARNING


# ---------------------------------------------------------------------------
# DD-1: _setup_logging console + file handler levels
# ---------------------------------------------------------------------------
def test_setup_logging_console_at_warning_when_not_verbose(_logger_state):
    root = logging.getLogger()
    before = set(root.handlers)
    m._setup_logging("INFO", verbose=False)
    consoles = _console_handlers(root, before)
    assert consoles, "expected a console StreamHandler"
    assert all(h.level == logging.WARNING for h in consoles)


def test_setup_logging_console_at_info_when_verbose(_logger_state):
    root = logging.getLogger()
    before = set(root.handlers)
    m._setup_logging("INFO", verbose=True)
    consoles = _console_handlers(root, before)
    assert consoles, "expected a console StreamHandler"
    assert all(h.level == logging.INFO for h in consoles)


def test_setup_logging_file_handler_at_info_when_not_verbose(_logger_state):
    root = logging.getLogger()
    before = set(root.handlers)
    m._setup_logging("INFO", verbose=False)
    # File handler is best-effort; tolerate absence if the dir isn't creatable.
    for h in _file_handlers(root, before):
        assert h.level == logging.INFO


@pytest.mark.parametrize("verbose", [False, True])
def test_setup_logging_file_handler_info_regardless_of_verbose(_logger_state, verbose):
    root = logging.getLogger()
    before = set(root.handlers)
    m._setup_logging("INFO", verbose=verbose)
    for h in _file_handlers(root, before):
        assert h.level == logging.INFO


# ---------------------------------------------------------------------------
# DD-2: _render_boot_summary collapsed vs verbose
# ---------------------------------------------------------------------------
def test_render_boot_summary_collapsed_has_no_per_pool_lines():
    lines = m._render_boot_summary(_sample_status(), verbose=False)
    assert not any("Pool [bold]" in ln for ln in lines)
    assert any("20 agents across 2 pools" in ln for ln in lines)
    assert any("Red team: 4 verification agents" in ln for ln in lines)


def test_render_boot_summary_verbose_has_per_pool_lines():
    lines = m._render_boot_summary(_sample_status(), verbose=True)
    assert any(
        "Pool [bold]filesystem[/bold]: 3 FileReaderAgent agents" in ln
        for ln in lines
    )
    assert any(
        "Pool [bold]shell[/bold]: 2 ShellCommandAgent agents" in ln
        for ln in lines
    )
    assert any("Red team: 4 verification agents" in ln for ln in lines)
    assert any("Total: 20 agents across 2 pools" in ln for ln in lines)


def test_render_boot_summary_degraded_pool_surfaces_when_collapsed():
    lines = m._render_boot_summary(_sample_status(degraded=True), verbose=False)
    # filesystem booted below target (1 < 3) → surfaces even in the collapse.
    assert any("Pool [bold]filesystem[/bold]" in ln for ln in lines)
    # healthy shell pool (2 == 2) stays collapsed.
    assert not any("Pool [bold]shell[/bold]" in ln for ln in lines)
    # the summary + red-team lines are still present.
    assert any("20 agents across 2 pools" in ln for ln in lines)
    assert any("Red team: 4 verification agents" in ln for ln in lines)


# ---------------------------------------------------------------------------
# DD-4: _boot_warning_count reflects WARNING+ and resets on fresh setup
# ---------------------------------------------------------------------------
def test_boot_warning_count_reflects_warnings_and_resets(_logger_state):
    m._setup_logging("INFO", verbose=False)
    assert m._boot_warning_count() == 0
    log = logging.getLogger("probos.test.ad1026")
    log.warning("boot notice")
    log.error("boot error")
    assert m._boot_warning_count() == 2
    # INFO is below the WARNING+ threshold and must not be counted.
    log.info("informational; not counted")
    assert m._boot_warning_count() == 2
    # A fresh _setup_logging resets the counter.
    m._setup_logging("INFO", verbose=False)
    assert m._boot_warning_count() == 0


# ---------------------------------------------------------------------------
# DD-3: argparse `serve --verbose` / `-v` threading
# ---------------------------------------------------------------------------
def _run_main_serve(monkeypatch, extra_argv: list[str]) -> dict:
    """Run ``main()`` for a ``serve`` invocation, capturing the kwargs that
    reach ``_serve`` (asserts BOTH the parser flag and the threading)."""
    captured: dict = {}

    async def _fake_serve(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(m, "_serve", _fake_serve)
    monkeypatch.setattr(sys, "argv", ["probos", "serve", *extra_argv])
    saved_policy = asyncio.get_event_loop_policy()
    try:
        m.main()
    finally:
        asyncio.set_event_loop_policy(saved_policy)
    return captured


def test_serve_verbose_long_flag_sets_true(monkeypatch):
    captured = _run_main_serve(monkeypatch, ["--verbose"])
    assert captured.get("verbose") is True


def test_serve_verbose_short_flag_sets_true(monkeypatch):
    captured = _run_main_serve(monkeypatch, ["-v"])
    assert captured.get("verbose") is True


def test_serve_without_verbose_flag_defaults_false(monkeypatch):
    captured = _run_main_serve(monkeypatch, [])
    assert captured.get("verbose") is False
