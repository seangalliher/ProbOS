"""AD-801: doctor runner — iterate checks, render results, return FAIL count."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.markup import escape

from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.doctor.registry import iter_checks

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# AD-1137: a string under a key holding one of these words is withheld from a config-load error.
_SECRET_KEY_WORDS = ("api_key", "token", "secret", "password")
# Shorter values are not withheld: they would redact ordinary words (such as "true") from the message.
_SECRET_MIN_CHARS = 8


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
    config_path: Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> DoctorContext:
    """Assemble the immutable context handed to every check.

    Config load failures don't abort the whole doctor run — the config
    check itself surfaces them, and downstream checks degrade gracefully
    when `ctx.config is None`. `home_dir` / `data_dir` overrides let
    callers (including tests + `__main__._cmd_doctor` honoring the
    AD-484 monkey-patch points) inject paths.

    AD-1137: `config_path` is the file to check; `__main__._cmd_doctor`
    passes the one `probos` and `probos serve` would load. Without it the
    AD-801 default, `home_dir / "config.yaml"`, stands. `transport` is
    handed to the provider probes (tests only).
    """
    home_dir = home_dir or _probos_home()
    data_dir = data_dir or _default_data_dir()
    target = config_path if config_path is not None else home_dir / "config.yaml"
    config = None
    error = ""
    if target.exists():
        try:
            from probos.config import load_config  # looked up per call: tests patch probos.config.load_config
            config = load_config(target)
        except Exception as exc:
            error = describe_load_failure(exc, target)
            # Not exc_info: the exception's own text can quote a value from the file (Pydantic's input_value).
            logger.debug("AD-1137: doctor could not load %s (%s: %s)", target, type(exc).__name__, error)

    return DoctorContext(
        config=config,
        home_dir=home_dir,
        data_dir=data_dir,
        config_path=target if target.exists() else None,
        config_target=target,
        config_error=error,
        provider_transport=transport,
    )


def describe_load_failure(exc: Exception, path: Path) -> str:
    """AD-1137: say why ``path`` did not load; settings are named, no value from the file is shown."""
    import yaml
    from pydantic import ValidationError

    from probos import provider_setup

    document = _parsed(path)
    if isinstance(exc, ValidationError):
        detail = "invalid settings: " + provider_setup.validation_summary(exc)
    elif isinstance(exc, yaml.YAMLError):
        mark = getattr(exc, "problem_mark", None)  # the YAML error's own text quotes the offending line
        detail = f"not valid YAML (line {mark.line + 1})" if mark is not None else "not valid YAML"
    elif isinstance(exc, UnicodeDecodeError):
        detail = "not valid UTF-8 text"
    elif isinstance(exc, OSError):
        detail = f"cannot be read ({type(exc).__name__})"
    elif document is not None and not isinstance(document, dict):
        detail = "its top level is not a mapping of config sections"  # load_config calls .items() on it
    else:
        detail = f"it did not load ({type(exc).__name__})"
    for secret in _secrets(document):
        detail = provider_setup.redact(detail, secret)
    return detail


def _parsed(path: Path) -> Any:
    """The YAML document in ``path``, or None when it cannot be read or parsed."""
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None


def _secrets(node: Any, under_secret_key: bool = False) -> list[str]:
    """Every string of at least ``_SECRET_MIN_CHARS`` held under a secret-like key in ``node``, longest first."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            secret_key = any(word in str(key).lower() for word in _SECRET_KEY_WORDS)
            found.update(_secrets(value, under_secret_key or secret_key))
    elif isinstance(node, list):
        for item in node:
            found.update(_secrets(item, under_secret_key))
    elif under_secret_key and isinstance(node, str) and len(node) >= _SECRET_MIN_CHARS:
        found.add(node)
    return sorted(found, key=lambda secret: (-len(secret), secret))


def _render(console: Console, name: str, outcome: CheckOutcome, message: str, remediation: str) -> None:
    """Render a single check's result with the appropriate glyph + style.

    AD-1137: check text is printed literally (a provider's or a path's "[" is not Rich markup),
    and each line of a multi-line remediation is indented under the result.
    """
    if outcome is CheckOutcome.OK:
        console.print(f"  [green]\u2713[/green] {escape(message)}")
        return
    if outcome is CheckOutcome.WARN:
        console.print(f"  [yellow]\u26a0[/yellow] {escape(message)}")
    else:  # FAIL
        console.print(f"  [red]\u2717[/red] {escape(message)}")
    for line in remediation.splitlines():
        console.print(f"    [dim]{escape(line)}[/dim]")


async def run_doctor(
    args: argparse.Namespace,
    console: Console,
    ctx: DoctorContext | None = None,
) -> int:
    """Run every registered doctor check; return FAIL count (0 = healthy).

    WARN does NOT contribute to the return code — only FAIL does. This
    mirrors the existing AD-484 contract that the test gate relies on
    (`probos doctor` exits 0 when nothing is broken even if some
    optional surface is missing). AD-1137 A-3: the closing line says
    "All checks passed." only when no check failed or warned.

    `ctx` lets the caller pre-build the context with overrides — used by
    `__main__._cmd_doctor` to honor the AD-484 monkey-patch points on
    `_probos_home` / `_default_data_dir`.
    """
    console.print("[bold blue]ProbOS Doctor[/bold blue]\n")

    if ctx is None:
        ctx = build_context()
    fail_count = 0
    warn_count = 0

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
        elif result.outcome is CheckOutcome.WARN:
            warn_count += 1

    console.print()
    if fail_count:
        console.print(f"[red]{fail_count} issue(s) found.[/red]")
    elif warn_count:  # AD-1137 A-3: a check that warned did not pass
        console.print(f"[yellow]No check failed; {warn_count} warning(s) above.[/yellow]")
    else:
        console.print("[green]All checks passed.[/green]")
    return fail_count
