"""AD-481h: /extensions shell command — extension subsystem management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_extensions(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """/extensions — extension subsystem management.

    Subcommands: list, enable, disable, remove, profile, info.
    """
    parts = args.split(maxsplit=1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "list":
        await _ext_list(runtime, console)
    elif sub == "enable":
        await _ext_enable(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "disable":
        await _ext_disable(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "remove":
        await _ext_remove(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "profile":
        await _ext_profile(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "info":
        await _ext_info(runtime, console, parts[1] if len(parts) > 1 else "")
    else:
        console.print("[yellow]Usage: /extensions <list|enable|disable|remove|profile|info>[/yellow]")
        console.print("  list                   — list all known extensions with state")
        console.print("  enable <id>            — enable a previously-disabled extension")
        console.print("  disable <id>           — disable an enabled extension (manifest preserved)")
        console.print("  remove <id>            — uninstall an extension")
        console.print("  profile <name>         — apply a profile (minimal/developer/full)")
        console.print("  info <id>              — show full manifest details")


async def _ext_list(runtime: "ProbOSRuntime", console: Console) -> None:
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available (extensions.enabled=False?).[/red]")
        return
    manifests = registry.list_extensions()
    if not manifests:
        console.print("[dim]No extensions registered.[/dim]")
        return
    table = Table(title="Registered Extensions")
    table.add_column("ID", style="cyan")
    table.add_column("Type")
    table.add_column("State", style="bold")
    table.add_column("Risk")
    table.add_column("Version")
    table.add_column("Description")
    for m in manifests:
        state = registry.get_state(m.extension_id)
        state_str = state.value if state else "unknown"
        table.add_row(
            m.extension_id,
            m.extension_type.value,
            state_str,
            m.risk_level.value,
            m.version,
            m.description[:60] + ("..." if len(m.description) > 60 else ""),
        )
    console.print(table)


async def _ext_enable(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions enable <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    try:
        await registry.enable(ext_id)
        console.print(f"[green]Enabled extension {ext_id!r}.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to enable {ext_id!r}: {exc}[/red]")


async def _ext_disable(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions disable <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    try:
        await registry.disable(ext_id)
        console.print(f"[green]Disabled extension {ext_id!r}.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to disable {ext_id!r}: {exc}[/red]")


async def _ext_remove(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions remove <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    try:
        await registry.remove(ext_id)
        console.print(f"[green]Removed extension {ext_id!r}.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to remove {ext_id!r}: {exc}[/red]")


async def _ext_profile(runtime: "ProbOSRuntime", console: Console, profile_name: str) -> None:
    if not profile_name:
        console.print("[yellow]Usage: /extensions profile <minimal|developer|full>[/yellow]")
        return
    from probos.extensions.profiles import apply_profile
    try:
        enable_list = apply_profile(profile_name)
    except Exception as exc:
        console.print(f"[red]Failed to load profile {profile_name!r}: {exc}[/red]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    enabled = 0
    disabled = 0
    enable_set = set(enable_list)
    for manifest in registry.list_extensions():
        try:
            if manifest.extension_id in enable_set:
                await registry.enable(manifest.extension_id)
                enabled += 1
            else:
                await registry.disable(manifest.extension_id)
                disabled += 1
        except Exception as exc:
            logger.warning(
                "Profile %s: failed to transition %s — %s",
                profile_name, manifest.extension_id, exc,
            )
    state_store = getattr(runtime, "extension_state_store", None)
    if state_store is not None:
        await state_store.set_profile(profile_name)
    console.print(
        f"[green]Applied profile {profile_name!r}: "
        f"{enabled} enabled, {disabled} disabled.[/green]"
    )


async def _ext_info(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions info <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    manifest = registry.get_manifest(ext_id)
    if manifest is None:
        console.print(f"[red]Unknown extension {ext_id!r}.[/red]")
        return
    state = registry.get_state(ext_id)
    console.print(f"[bold cyan]{manifest.name}[/bold cyan] ({manifest.extension_id})")
    console.print(f"  type:           {manifest.extension_type.value}")
    console.print(f"  state:          {state.value if state else 'unknown'}")
    console.print(f"  risk:           {manifest.risk_level.value}")
    console.print(f"  version:        {manifest.version}")
    console.print(f"  required API:   {manifest.required_api_version}")
    console.print(f"  author:         {manifest.author or '-'}")
    console.print(f"  license:        {manifest.license or '-'}")
    console.print(f"  description:    {manifest.description or '-'}")
    if manifest.dependencies:
        console.print(f"  dependencies:   {', '.join(manifest.dependencies)}")
