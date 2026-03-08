"""ProbOS entry point — boot runtime and launch interactive shell.

Usage::

    uv run python -m probos
    uv run python -m probos --config config/node-1.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.config import load_config
from probos.runtime import ProbOSRuntime
from probos.experience.shell import ProbOSShell


def _setup_logging(log_level: str) -> None:
    """Configure logging for shell mode — suppress noisy output."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep the noise down while the shell is active — the Rich UI
    # already shows execution progress visually.
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("probos.substrate.agent").setLevel(logging.WARNING)
    logging.getLogger("probos.federation").setLevel(logging.WARNING)
    logging.getLogger("probos.cognitive.decomposer").setLevel(logging.WARNING)
    logging.getLogger("probos.mesh.intent").setLevel(logging.WARNING)
    logging.getLogger("probos.mesh.routing").setLevel(logging.WARNING)
    logging.getLogger("probos.substrate.spawner").setLevel(logging.WARNING)
    logging.getLogger("probos.substrate.pool").setLevel(logging.WARNING)


async def _create_llm_client(config, console: Console):
    """Create an LLM client from config, falling back to MockLLMClient."""
    cog = config.cognitive
    client = OpenAICompatibleClient(config=cog)

    console.print("  Checking LLM endpoints...")
    connectivity = await client.check_connectivity()

    for tier in ("fast", "standard", "deep"):
        tc = cog.tier_config(tier)
        reachable = connectivity[tier]
        if reachable:
            console.print(
                f"  [green]\u2713[/green] LLM {tier}: {tc['model']} at {tc['base_url']}"
            )
        else:
            console.print(
                f"  [yellow]\u2717[/yellow] LLM {tier}: {tc['base_url']} unreachable"
            )

    if not any(connectivity.values()):
        # All endpoints unreachable — fall back to mock
        await client.close()
        console.print(
            "  [yellow]\u26a0[/yellow] No LLM endpoints reachable. "
            "Falling back to [bold]MockLLMClient[/bold] "
            "(pattern-matched responses only)."
        )
        return MockLLMClient()

    if not all(connectivity.values()):
        down_tiers = [t for t, r in connectivity.items() if not r]
        console.print(
            f"  [yellow]\u26a0 Warning: {', '.join(down_tiers)} tier(s) unreachable[/yellow]"
        )

    return client


async def _boot_and_run(config_path: Path | None = None) -> None:
    console = Console()

    # Banner
    banner = Text()
    banner.append("ProbOS", style="bold blue")
    banner.append(" v0.1.0", style="dim")
    banner.append(" \u2014 Probabilistic Agent-Native OS", style="italic")
    console.print(Panel(banner, style="blue"))
    console.print()

    # Load config
    if config_path is None:
        project_root = Path(__file__).resolve().parent.parent.parent
        config_path = project_root / "config" / "system.yaml"
    config = load_config(config_path)

    _setup_logging(config.system.log_level)

    with tempfile.TemporaryDirectory(prefix="probos_") as tmp:
        # Create LLM client with connectivity check
        console.print("[bold blue]Starting ProbOS...[/bold blue]")
        llm_client = await _create_llm_client(config, console)

        # Create episodic memory
        episodic_db = Path(tmp) / "episodic.db"
        episodic_memory = EpisodicMemory(
            db_path=str(episodic_db),
            max_episodes=config.memory.max_episodes,
        )

        runtime = ProbOSRuntime(
            config=config, data_dir=tmp, llm_client=llm_client,
            episodic_memory=episodic_memory,
        )

        # Boot sequence
        with console.status("  Initializing infrastructure..."):
            await runtime.start()

        # Show what was created
        status = runtime.status()
        for name, pool in runtime.pools.items():
            info = pool.info()
            console.print(
                f"  [green]\u2713[/green] Pool [bold]{name}[/bold]: "
                f"{info['current_size']} {info['agent_type']} agents"
            )
        console.print(
            f"  [green]\u2713[/green] Red team: "
            f"{status['consensus']['red_team_agents']} verification agents"
        )
        console.print(
            f"  [green]\u2713[/green] Total: "
            f"{status['total_agents']} agents across "
            f"{len(status['pools'])} pools"
        )
        console.print()
        console.print("[bold green]ProbOS ready.[/bold green]")
        console.print(
            "[dim]Type /help for commands, or enter a natural language request.[/dim]"
        )
        console.print()

        # Interactive shell
        shell = ProbOSShell(runtime, console)
        try:
            await shell.run()
        finally:
            with console.status("[bold red]Shutting down...[/bold red]"):
                await runtime.stop()
            console.print("[dim]ProbOS stopped.[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="ProbOS — Probabilistic Agent-Native OS")
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=None,
        help="Path to config YAML (default: config/system.yaml)",
    )
    args = parser.parse_args()

    # Windows ProactorEventLoop doesn't support add_reader required by pyzmq.
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(_boot_and_run(config_path=args.config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
