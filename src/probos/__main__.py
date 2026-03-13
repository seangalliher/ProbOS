"""ProbOS entry point — boot runtime and launch interactive shell or API server.

Usage::

    probos                  # interactive shell (default)
    probos init             # create ~/.probos/ config
    probos serve            # HTTP + WebSocket API server
    probos serve --interactive  # API server + interactive shell
    probos --config config/node-1.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.config import load_config
from probos.runtime import ProbOSRuntime
from probos.experience.shell import ProbOSShell


def _default_data_dir() -> Path:
    """Return a stable, platform-appropriate data directory."""
    import sys
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "ProbOS"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "ProbOS"
    else:
        # XDG_DATA_HOME or ~/.local/share
        import os
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) / "ProbOS" if xdg else Path.home() / ".local" / "share" / "ProbOS"
    return base / "data"


def _probos_home() -> Path:
    """Return ~/.probos path."""
    return Path.home() / ".probos"


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


async def _ensure_ollama(config, console: Console) -> None:
    """Start Ollama if needed and warm up the model.

    1. Check if the Ollama server is reachable.
    2. If not, find and start ``ollama serve``, wait for readiness.
    3. Send a lightweight request to load the model into VRAM.
    """
    import httpx

    # Collect Ollama tier configs
    ollama_tiers: list[dict] = []
    for tier in ("fast", "standard", "deep"):
        tc = config.cognitive.tier_config(tier)
        if tc.get("api_format") == "ollama":
            ollama_tiers.append(tc)

    if not ollama_tiers:
        return  # No Ollama tiers configured

    # Deduplicate URLs
    ollama_urls: list[str] = list(dict.fromkeys(tc["base_url"].rstrip("/") for tc in ollama_tiers))
    url = ollama_urls[0]

    console.print("  [dim]Checking Ollama...[/dim]")

    # Step 1: Check if the server is reachable
    server_up = False
    try:
        async with httpx.AsyncClient(base_url=url + "/", timeout=3.0) as client:
            resp = await client.get("api/version")
            if resp.status_code < 500:
                server_up = True
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        pass

    # Step 2: Start the server if needed
    if not server_up:
        ollama_bin = shutil.which("ollama")
        if not ollama_bin:
            console.print("  [yellow]\u26a0 Ollama not found on PATH — cannot auto-start[/yellow]")
            return

        console.print("  [yellow]Ollama is not running — starting it...[/yellow]")
        try:
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            console.print(f"  [red]Failed to start Ollama: {exc}[/red]")
            return

        # Wait for server to become reachable
        with console.status("  Waiting for Ollama server...") as status:
            for attempt in range(30):  # up to 15 seconds
                await asyncio.sleep(0.5)
                try:
                    async with httpx.AsyncClient(base_url=url + "/", timeout=2.0) as client:
                        resp = await client.get("api/version")
                        if resp.status_code < 500:
                            server_up = True
                            break
                except (httpx.ConnectError, httpx.TimeoutException, OSError):
                    pass

        if not server_up:
            console.print("  [yellow]\u26a0 Ollama started but not reachable — continuing anyway[/yellow]")
            return

        console.print("  [green]\u2713[/green] Ollama server started")
    else:
        console.print("  [green]\u2713[/green] Ollama server is running")

    # Step 3: Warm up each model so it's loaded in VRAM
    keep_alive = getattr(config.cognitive, "ollama_keep_alive", "30m")
    for tc in ollama_tiers:
        model = tc["model"]
        base = tc["base_url"].rstrip("/")
        console.print(f"  [dim]Warming up model [bold]{model}[/bold]...[/dim]")
        try:
            async with httpx.AsyncClient(base_url=base + "/", timeout=120.0) as client:
                resp = await client.post(
                    "api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                        "think": False,
                        "keep_alive": keep_alive,
                    },
                )
                if resp.status_code < 400:
                    console.print(f"  [green]\u2713[/green] Model [bold]{model}[/bold] loaded")
                else:
                    console.print(f"  [yellow]\u26a0 Model {model}: HTTP {resp.status_code}[/yellow]")
        except httpx.TimeoutException:
            console.print(f"  [yellow]\u26a0 Model {model} warm-up timed out (may still be loading)[/yellow]")
        except (httpx.ConnectError, OSError) as exc:
            console.print(f"  [yellow]\u26a0 Model {model} warm-up failed: {exc}[/yellow]")


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


def _load_config_with_fallback(config_path: Path | None) -> tuple:
    """Load config from the provided path, ~/.probos, or project default."""
    if config_path is not None:
        return load_config(config_path), config_path

    # Try ~/.probos/config.yaml first
    home_config = _probos_home() / "config.yaml"
    if home_config.exists():
        return load_config(home_config), home_config

    # Fall back to project-bundled config
    project_root = Path(__file__).resolve().parent.parent.parent
    default_path = project_root / "config" / "system.yaml"
    return load_config(default_path), default_path


async def _boot_runtime(
    config_path: Path | None = None,
    fresh: bool = False,
    data_dir: Path | None = None,
    console: Console | None = None,
) -> tuple:
    """Boot the runtime and return (runtime, config, console)."""
    if console is None:
        console = Console()

    # Banner
    banner = Text()
    banner.append("ProbOS", style="bold blue")
    banner.append(" v0.1.0", style="dim")
    banner.append(" \u2014 Probabilistic Agent-Native OS", style="italic")
    console.print(Panel(banner, style="blue"))
    console.print()

    # Load config
    config, resolved_path = _load_config_with_fallback(config_path)

    # --fresh flag: override restore_on_boot (AD-165)
    if fresh:
        config.knowledge.restore_on_boot = False

    _setup_logging(config.system.log_level)

    # Use stable data directory (not temp)
    data_path = data_dir or _default_data_dir()
    data_path = Path(data_path)
    data_path.mkdir(parents=True, exist_ok=True)
    console.print(f"  Data dir: [dim]{data_path}[/dim]")

    # Ensure Ollama is running before LLM client creation
    await _ensure_ollama(config, console)

    # Create LLM client with connectivity check
    console.print("[bold blue]Starting ProbOS...[/bold blue]")
    llm_client = await _create_llm_client(config, console)

    # Create episodic memory (ChromaDB-backed, uses data_dir for persistence)
    episodic_db = data_path / "episodic.db"
    episodic_memory = EpisodicMemory(
        db_path=str(episodic_db),
        max_episodes=config.memory.max_episodes,
        relevance_threshold=config.memory.relevance_threshold,
    )

    runtime = ProbOSRuntime(
        config=config, data_dir=str(data_path), llm_client=llm_client,
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

    return runtime, config, console


async def _boot_and_run(config_path: Path | None = None, fresh: bool = False, data_dir: Path | None = None) -> None:
    """Boot runtime and launch interactive shell."""
    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir)

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


async def _serve(
    config_path: Path | None = None,
    fresh: bool = False,
    data_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 18900,
    interactive: bool = False,
) -> None:
    """Boot runtime and start the FastAPI/uvicorn server."""
    import uvicorn
    from probos.api import create_app

    console = Console()
    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console)

    app = create_app(runtime)

    uv_config = uvicorn.Config(
        app, host=host, port=port, log_level="warning",
    )
    server = uvicorn.Server(uv_config)

    console.print(
        f"  [green]\u2713[/green] API server listening on "
        f"[bold]http://{host}:{port}[/bold]"
    )
    console.print(
        f"  [dim]POST /api/chat  |  GET /api/status  |  "
        f"GET /api/health  |  WS /ws/events[/dim]"
    )

    # Open HXI in browser (AD-260)
    import webbrowser
    webbrowser.open(f"http://{host}:{port}")

    console.print()

    try:
        if interactive:
            # Run API server + interactive shell concurrently
            shell = ProbOSShell(runtime, console)
            console.print(
                "[dim]Type /help for commands, or enter a natural language request.[/dim]"
            )
            console.print()
            server_task = asyncio.create_task(server.serve())
            try:
                await shell.run()
            finally:
                server.should_exit = True
                await server_task
        else:
            console.print("[dim]Press Ctrl+C to stop.[/dim]")
            console.print()
            await server.serve()
    finally:
        with console.status("[bold red]Shutting down...[/bold red]"):
            await runtime.stop()
        console.print("[dim]ProbOS stopped.[/dim]")


def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``probos init`` — create ~/.probos/ with default config."""
    console = Console()
    home = Path(args.probos_home) if args.probos_home else _probos_home()

    if (home / "config.yaml").exists() and not args.force:
        console.print(
            f"[yellow]Config already exists at {home / 'config.yaml'}[/yellow]\n"
            f"Use [bold]--force[/bold] to overwrite."
        )
        return

    console.print("[bold blue]ProbOS Init[/bold blue]")
    console.print()

    # Prompt for LLM endpoint
    default_url = "http://127.0.0.1:11434"
    llm_url = input(f"  LLM endpoint URL [{default_url}]: ").strip() or default_url

    # Prompt for model
    default_model = "qwen3.5:35b"
    llm_model = input(f"  LLM model [{default_model}]: ").strip() or default_model

    # Auto-detect API format from URL
    api_format = "ollama" if ":11434" in llm_url else "openai"

    # Create directories
    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    (home / "notes").mkdir(exist_ok=True)

    # Write config
    config_content = f"""\
# ProbOS Configuration — generated by `probos init`
system:
  name: "ProbOS"
  version: "0.1.0"
  log_level: "WARNING"

cognitive:
  default_llm_tier: "fast"
  llm_base_url_fast: "{llm_url}"
  llm_api_key_fast: ""
  llm_model_fast: "{llm_model}"
  llm_api_format_fast: "{api_format}"

self_mod:
  enabled: true

knowledge:
  enabled: true
  repo_path: "{(home / 'knowledge').as_posix()}"

bundled_agents:
  enabled: true
"""
    (home / "config.yaml").write_text(config_content, encoding="utf-8")

    console.print()
    console.print(f"  [green]\u2713[/green] Created [bold]{home}[/bold]")
    console.print(f"  [green]\u2713[/green] Config: [dim]{home / 'config.yaml'}[/dim]")
    console.print(f"  [green]\u2713[/green] Data dir: [dim]{home / 'data'}[/dim]")
    console.print()
    console.print("ProbOS initialized. Run [bold]probos serve[/bold] to start.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ProbOS \u2014 Probabilistic Agent-Native OS",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- Default (no subcommand) args on the main parser ---
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=None,
        help="Path to config YAML (default: ~/.probos/config.yaml or config/system.yaml)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Cold start: ignore existing knowledge repo (AD-165)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Persistent data directory (default: platform-specific)",
    )

    # --- probos init ---
    init_parser = subparsers.add_parser("init", help="Initialize ProbOS config at ~/.probos/")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config")
    init_parser.add_argument("--probos-home", type=str, default=None, help="Custom config directory")

    # --- probos serve ---
    serve_parser = subparsers.add_parser("serve", help="Start HTTP + WebSocket API server")
    serve_parser.add_argument(
        "--config", "-c", type=Path, default=None,
        help="Path to config YAML",
    )
    serve_parser.add_argument("--fresh", action="store_true", help="Cold start")
    serve_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address")
    serve_parser.add_argument("--port", type=int, default=18900, help="Bind port")
    serve_parser.add_argument("--interactive", action="store_true", help="Also run interactive shell")

    args = parser.parse_args()

    # Windows ProactorEventLoop doesn't support add_reader required by pyzmq.
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if args.command == "init":
        _cmd_init(args)
        return

    if args.command == "serve":
        try:
            asyncio.run(_serve(
                config_path=args.config,
                fresh=args.fresh,
                data_dir=args.data_dir,
                host=args.host,
                port=args.port,
                interactive=args.interactive,
            ))
        except KeyboardInterrupt:
            pass
        return

    # Default: interactive shell (backward compatible)
    try:
        asyncio.run(_boot_and_run(config_path=args.config, fresh=args.fresh, data_dir=args.data_dir))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
