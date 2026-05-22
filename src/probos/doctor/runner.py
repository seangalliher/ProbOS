"""AD-801: doctor runner — iterate checks, render results, return FAIL count."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rich.console import Console

from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.doctor.registry import iter_checks

logger = logging.getLogger(__name__)


def _probos_home() -> Path:
    """Resolve `~/.probos/` — used only when the caller doesn't inject a context."""
    return Path.home() / ".probos"


def _default_data_dir() -> Path:
    """Resolve the default data dir — used only when the caller doesn't inject a context."""
    import os
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ProbOS" / "data"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "probos"
    return base


def build_context(
    home_dir: Path | None = None,
    data_dir: Path | None = None,
) -> DoctorContext:
    """Assemble the immutable context handed to every check.

    Config load failures don't abort the whole doctor run — the config
    check itself surfaces them, and downstream checks degrade gracefully
    when `ctx.config is None`. `home_dir` / `data_dir` overrides let
    callers (including tests + `__main__._cmd_doctor` honoring the
    AD-484 monkey-patch points) inject paths.
    """
    home_dir = home_dir or _probos_home()
    data_dir = data_dir or _default_data_dir()
    config_path = home_dir / "config.yaml"
    config = None
    if config_path.exists():
        try:
            from probos.config import load_config
            config = load_config(config_path)
        except Exception as exc:
            logger.debug("AD-801: config load failed: %s", exc, exc_info=True)

    return DoctorContext(
        config=config,
        home_dir=home_dir,
        data_dir=data_dir,
        config_path=config_path if config_path.exists() else None,
    )


def _render(console: Console, name: str, outcome: CheckOutcome, message: str, remediation: str) -> None:
    """Render a single check's result with the appropriate glyph + style."""
    if outcome is CheckOutcome.OK:
        console.print(f"  [green]\u2713[/green] {message}")
        return
    if outcome is CheckOutcome.WARN:
        console.print(f"  [yellow]\u26a0[/yellow] {message}")
    else:  # FAIL
        console.print(f"  [red]\u2717[/red] {message}")
    if remediation:
        console.print(f"    [dim]{remediation}[/dim]")


async def run_doctor(
    args: argparse.Namespace,
    console: Console,
    ctx: DoctorContext | None = None,
) -> int:
    """Run every registered doctor check; return FAIL count (0 = healthy).

    WARN does NOT contribute to the return code — only FAIL does. This
    mirrors the existing AD-484 contract that the test gate relies on
    (`probos doctor` exits 0 when nothing is broken even if some
    optional surface is missing).

    `ctx` lets the caller pre-build the context with overrides — used by
    `__main__._cmd_doctor` to honor the AD-484 monkey-patch points on
    `_probos_home` / `_default_data_dir`.
    """
    console.print("[bold blue]ProbOS Doctor[/bold blue]\n")

    if ctx is None:
        ctx = build_context()
    fail_count = 0

    for check in iter_checks():
        try:
            result = await check.run(ctx)
        except Exception as exc:
            logger.warning(
                "AD-801: doctor check '%s' raised; treating as FAIL",
                check.name, exc_info=True,
            )
            _render(
                console,
                check.name,
                CheckOutcome.FAIL,
                f"{check.name}: check raised {type(exc).__name__}",
                f"See logs for traceback: {exc}",
            )
            fail_count += 1
            continue
        _render(console, check.name, result.outcome, result.message, result.remediation)
        if result.outcome is CheckOutcome.FAIL:
            fail_count += 1

    console.print()
    if fail_count:
        console.print(f"[red]{fail_count} issue(s) found.[/red]")
    else:
        console.print("[green]All checks passed.[/green]")
    return fail_count
