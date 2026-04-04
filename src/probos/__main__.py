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
import os
import re
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
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

    # AD-541f: Create eviction audit log
    eviction_audit = None
    if config.memory.eviction_audit_enabled:
        from probos.cognitive.eviction_audit import EvictionAuditLog
        eviction_audit = EvictionAuditLog()

    # Create episodic memory (ChromaDB-backed, uses data_dir for persistence)
    episodic_db = data_path / "episodic.db"
    episodic_memory = EpisodicMemory(
        db_path=str(episodic_db),
        max_episodes=config.memory.max_episodes,
        relevance_threshold=config.memory.relevance_threshold,
        verify_content_hash=config.memory.verify_content_hash,
        eviction_audit=eviction_audit,
    )

    runtime = ProbOSRuntime(
        config=config, data_dir=str(data_path), llm_client=llm_client,
        episodic_memory=episodic_memory,
    )
    runtime._eviction_audit = eviction_audit  # AD-541f: expose for shutdown/SIF

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
        console.print("\n[bold red]ProbOS shutting down...[/bold red]")
        console.print("  [dim]Stopping runtime...[/dim]", end="")
        try:
            await asyncio.wait_for(runtime.stop(reason=getattr(shell, '_quit_reason', '')), timeout=5)
            console.print(" [green]done[/green]")
        except asyncio.TimeoutError:
            console.print(" [yellow]timed out (5s)[/yellow]")
        except Exception as e:
            console.print(f" [yellow]warn: {e}[/yellow]")
        finally:
            console.print("[dim]ProbOS stopped.[/dim]")
            os._exit(0)


async def _serve(
    config_path: Path | None = None,
    fresh: bool = False,
    data_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 18900,
    interactive: bool = False,
    discord: bool = False,
) -> None:
    """Boot runtime and start the FastAPI/uvicorn server."""
    import uvicorn
    from probos.api import create_app

    console = Console()
    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console)

    if fresh:
        runtime._fresh_boot = True
        runtime._lifecycle_state = "reset"  # AD-502: --fresh flag = explicit reset

    app = create_app(runtime)

    # Start channel adapters
    adapters: list = []
    if discord or config.channels.discord.enabled:
        from probos.channels.discord_adapter import DiscordAdapter
        discord_cfg = config.channels.discord
        token = os.environ.get("PROBOS_DISCORD_TOKEN", "") or discord_cfg.token
        if token:
            discord_cfg = discord_cfg.model_copy(update={"token": token})
            adapter = DiscordAdapter(runtime, discord_cfg)
            await adapter.start()
            if adapter._started:
                adapters.append(adapter)
                console.print("  [green]\u2713[/green] Discord bot adapter started")
            else:
                console.print("  [red]\u2717[/red] Discord adapter failed — run: uv sync --extra discord")
        else:
            console.print("  [yellow]![/yellow] Discord enabled but no token set (PROBOS_DISCORD_TOKEN)")

    # Wire channel adapters into task scheduler for delivery (AD-284)
    if adapters and runtime.task_scheduler:
        runtime.task_scheduler._channel_adapters = adapters

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
        console.print("\n[bold red]ProbOS shutting down...[/bold red]")
        for adapter in adapters:
            name = type(adapter).__name__
            console.print(f"  [dim]Stopping {name}...[/dim]", end="")
            try:
                await asyncio.wait_for(adapter.stop(), timeout=5)
                console.print(" [green]done[/green]")
            except asyncio.TimeoutError:
                console.print(" [yellow]timed out (5s)[/yellow]")
            except (KeyboardInterrupt, SystemExit):
                console.print(" [yellow]interrupted[/yellow]")
            except Exception as e:
                console.print(f" [yellow]warn: {e}[/yellow]")
        console.print("  [dim]Stopping runtime...[/dim]", end="")
        try:
            await asyncio.wait_for(runtime.stop(), timeout=5)
            console.print(" [green]done[/green]")
        except asyncio.TimeoutError:
            console.print(" [yellow]timed out (5s)[/yellow]")
        except (KeyboardInterrupt, SystemExit):
            console.print(" [yellow]interrupted[/yellow]")
        except Exception as e:
            console.print(f" [yellow]warn: {e}[/yellow]")
        finally:
            console.print("[dim]ProbOS stopped.[/dim]")
            os._exit(0)


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
    default_url = "http://127.0.0.1:8080/v1"
    llm_url = input(f"  LLM endpoint URL [{default_url}]: ").strip() or default_url

    # Prompt for model
    default_model = "claude-sonnet-4-20250514"
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

utility_agents:
  enabled: true
"""
    (home / "config.yaml").write_text(config_content, encoding="utf-8")

    console.print()
    console.print(f"  [green]\u2713[/green] Created [bold]{home}[/bold]")
    console.print(f"  [green]\u2713[/green] Config: [dim]{home / 'config.yaml'}[/dim]")
    console.print(f"  [green]\u2713[/green] Data dir: [dim]{home / 'data'}[/dim]")
    console.print()
    console.print("ProbOS initialized. Run [bold]probos serve[/bold] to start.")


_RESET_SUBDIRS = ("episodes", "agents", "skills", "trust", "routing", "workflows", "qa")

# ── Tiered Reset Architecture (BF-070) ──────────────────────────────
# Each tier is cumulative: Tier N includes all tiers 1..N-1.

RESET_TIERS = {
    1: {
        "name": "Reboot",
        "flag": "--soft",
        "description": "Runtime transients — safe, timeline intact",
        "files": ["scheduled_tasks.db", "events.db"],
        "dirs": ["checkpoints"],
        # NOTE: session_last.json is NOT here — soft reset preserves stasis detection
    },
    2: {
        "name": "Recommissioning",
        "flag": "(default)",
        "description": "New ship, new crew — maiden voyage",
        "files": [
            # Cognition (former Shore Leave)
            "session_last.json", "chroma.sqlite3", "cognitive_journal.db",
            "hebbian_weights.db", "trust.db", "service_profiles.db",
            # Identity
            "identity.db", "acm.db", "skills.db", "directives.db",
            "assignments.db",
        ],
        "dirs": ["semantic"],
        "special": ["chromadb_uuid_dirs", "knowledge_subdirs", "ontology_instance_id"],
    },
    3: {
        "name": "Maiden Voyage",
        "flag": "--full",
        "description": "Institutional knowledge — organizational memory lost",
        "files": ["ward_room.db", "workforce.db"],
        "dirs": ["ship-records", "scout_reports"],
        "archive_first": ["ward_room.db"],
    },
}

# Files that are NEVER cleared by any tier
_ALWAYS_PRESERVED = ["archives/"]


def _get_file_size(path: Path) -> str:
    """Return a human-readable size string for a file or directory."""
    if not path.exists():
        return ""
    if path.is_file():
        size = path.stat().st_size
    elif path.is_dir():
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    else:
        return ""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


def _resolve_tier(args: argparse.Namespace) -> int:
    """Determine effective tier from CLI flags."""
    if getattr(args, 'soft', False):
        return 1
    elif getattr(args, 'full', False) or getattr(args, 'wipe_records', False):
        return 3
    else:
        return 2  # default: Recommissioning


def _collect_tier_targets(tier: int, data_dir: Path) -> dict[int, list[tuple[str, str, str]]]:
    """Collect files/dirs to clear for each tier up to the given tier.

    Returns {tier_num: [(display_name, description, size_str), ...]}.
    """
    result: dict[int, list[tuple[str, str, str]]] = {}

    for t in range(1, tier + 1):
        tier_def = RESET_TIERS[t]
        items: list[tuple[str, str, str]] = []

        for fname in tier_def.get("files", []):
            fpath = data_dir / fname
            size = _get_file_size(fpath)
            items.append((fname, _file_purpose(fname), size))

        for dname in tier_def.get("dirs", []):
            dpath = data_dir / dname
            if dpath.is_dir():
                n_items = len(list(dpath.iterdir()))
                items.append((dname + "/", _file_purpose(dname), f"{n_items} item(s)"))
            else:
                items.append((dname + "/", _file_purpose(dname), ""))

        for special in tier_def.get("special", []):
            if special == "chromadb_uuid_dirs":
                uuid_dirs = _find_chromadb_uuid_dirs(data_dir)
                if uuid_dirs:
                    items.append(("<uuid>/ dirs", "ChromaDB HNSW indexes", f"{len(uuid_dirs)} dir(s)"))
            elif special == "knowledge_subdirs":
                items.append(("knowledge/ subdirs", "Operational state", ""))
            elif special == "ontology_instance_id":
                fpath = data_dir / "ontology" / "instance_id"
                items.append(("ontology/instance_id", "Ship DID", _get_file_size(fpath)))

        result[t] = items

    return result


def _file_purpose(name: str) -> str:
    """Return a short description of what a file/dir stores."""
    purposes = {
        "session_last.json": "Session record",
        "scheduled_tasks.db": "Scheduled tasks",
        "events.db": "Event log",
        "checkpoints": "DAG checkpoints",
        "chroma.sqlite3": "Episodic memory",
        "cognitive_journal.db": "Cognitive journal",
        "hebbian_weights.db": "Hebbian weights",
        "trust.db": "Trust network",
        "service_profiles.db": "Service profiles",
        "semantic": "Semantic indexes",
        "identity.db": "Identity registry",
        "acm.db": "Agent Capital Mgmt",
        "skills.db": "Skill registry",
        "directives.db": "Standing orders",
        "ward_room.db": "Ward Room",
        "workforce.db": "Workforce data",
        "ship-records": "Ship's Records",
        "scout_reports": "Scout reports",
    }
    return purposes.get(name, name)


def _find_chromadb_uuid_dirs(data_dir: Path) -> list[Path]:
    """Find UUID-named directories in data_dir (ChromaDB HNSW indexes)."""
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE,
    )
    result = []
    if data_dir.is_dir():
        for entry in data_dir.iterdir():
            if entry.is_dir() and uuid_pattern.match(entry.name):
                result.append(entry)
    return result


def _show_confirmation_prompt(tier: int, data_dir: Path, active_task_count: int, console: Console) -> bool:
    """Show Rich confirmation prompt with tier details. Returns True if user confirms."""
    tier_names = {1: "Reboot", 2: "Recommissioning", 3: "Maiden Voyage"}
    targets = _collect_tier_targets(tier, data_dir)

    tier_labels = {
        1: "Tier 1 — Runtime Transients",
        2: "Tier 2 — Cognition + Identity",
        3: "Tier 3 — Institutional Knowledge",
    }

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Name", style="bold")
    table.add_column("Purpose", style="dim")
    table.add_column("Size", style="dim", justify="right")

    # What will be cleared
    for t in range(1, tier + 1):
        items = targets.get(t, [])
        table.add_row(f"\n[bold]{tier_labels[t]}[/bold]", "", "")
        for name, purpose, size in items:
            table.add_row(f"  • {name}", purpose, size)

    # What will be preserved
    preserved_items = []
    for t in range(tier + 1, 4):
        for fname in RESET_TIERS[t].get("files", []):
            fpath = data_dir / fname
            preserved_items.append((fname, _file_purpose(fname), _get_file_size(fpath)))
        for dname in RESET_TIERS[t].get("dirs", []):
            preserved_items.append((dname + "/", _file_purpose(dname), ""))
    # Always preserved
    preserved_items.append(("archives/", "Ward Room backups", ""))

    if preserved_items:
        table.add_row("\n[bold green]Preserved:[/bold green]", "", "")
        for name, purpose, size in preserved_items:
            table.add_row(f"  • {name}", purpose, size)

    panel = Panel(
        table,
        title=f"ProbOS Reset: Tier {tier} — {tier_names[tier]}",
        subtitle="Continue? [y/N]",
        style="yellow" if tier == 1 else ("red" if tier == 3 else "bold"),
    )
    console.print(panel)

    if active_task_count > 0:
        console.print(
            f"  [yellow]⚠  {active_task_count} active scheduled task(s) will fire post-reset "
            "with degraded routing.[/yellow]"
        )

    answer = input("  Continue? [y/N]: ").strip().lower()
    return answer == "y"


def _show_dry_run(tier: int, data_dir: Path, active_task_count: int, console: Console) -> None:
    """Show what would be cleared without making changes."""
    _show_confirmation_prompt.__wrapped__ = True  # just reuse the display
    tier_names = {1: "Reboot", 2: "Recommissioning", 3: "Maiden Voyage"}
    targets = _collect_tier_targets(tier, data_dir)

    tier_labels = {
        1: "Tier 1 — Runtime Transients",
        2: "Tier 2 — Cognition + Identity",
        3: "Tier 3 — Institutional Knowledge",
    }

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Name", style="bold")
    table.add_column("Purpose", style="dim")
    table.add_column("Size", style="dim", justify="right")

    for t in range(1, tier + 1):
        items = targets.get(t, [])
        table.add_row(f"\n[bold]{tier_labels[t]}[/bold]", "", "")
        for name, purpose, size in items:
            table.add_row(f"  • {name}", purpose, size)

    preserved_items = []
    for t in range(tier + 1, 4):
        for fname in RESET_TIERS[t].get("files", []):
            fpath = data_dir / fname
            preserved_items.append((fname, _file_purpose(fname), _get_file_size(fpath)))
        for dname in RESET_TIERS[t].get("dirs", []):
            preserved_items.append((dname + "/", _file_purpose(dname), ""))
    preserved_items.append(("archives/", "Ward Room backups", ""))

    if preserved_items:
        table.add_row("\n[bold green]Preserved:[/bold green]", "", "")
        for name, purpose, size in preserved_items:
            table.add_row(f"  • {name}", purpose, size)

    panel = Panel(
        table,
        title=f"[DRY RUN] ProbOS Reset: Tier {tier} — {tier_names[tier]}",
        subtitle="[DRY RUN] No changes made.",
        style="dim",
    )
    console.print(panel)

    if active_task_count > 0:
        console.print(
            f"  [yellow]⚠  {active_task_count} active scheduled task(s) would fire post-reset "
            "with degraded routing.[/yellow]"
        )
    console.print("\n  [dim][DRY RUN] No changes made.[/dim]")


def _cmd_reset(args: argparse.Namespace) -> None:
    """Handle ``probos reset`` — tiered reset system (BF-070)."""
    console = Console()

    # Deprecated flag notice
    if getattr(args, 'wipe_records', False):
        console.print("[yellow]⚠ --wipe-records is deprecated, use --full[/yellow]")

    # Load config to find knowledge repo_path
    config, _ = _load_config_with_fallback(getattr(args, 'config', None))
    repo_path = Path(config.knowledge.repo_path).expanduser() if config.knowledge.repo_path else Path.home() / ".probos" / "knowledge"
    data_dir = getattr(args, 'data_dir', None) or _default_data_dir()
    data_dir = Path(data_dir)

    # Use data_dir-based knowledge path if the config path doesn't exist
    data_dir_knowledge = data_dir / "knowledge"
    if not repo_path.is_dir() and data_dir_knowledge.is_dir():
        repo_path = data_dir_knowledge

    # Resolve the effective tier
    tier = _resolve_tier(args)

    # AD-418: Check for active scheduled tasks that survive reset
    scheduled_db = data_dir / "scheduled_tasks.db"
    active_task_count = 0
    if scheduled_db.is_file():
        import sqlite3
        conn = None
        try:
            conn = sqlite3.connect(str(scheduled_db))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM scheduled_tasks "
                "WHERE enabled = 1 AND status = 'pending' AND schedule_type != 'once'"
            )
            row = cursor.fetchone()
            active_task_count = row["cnt"] if row else 0
        except Exception:
            pass  # DB may not exist yet — best-effort count
        finally:
            if conn:
                conn.close()

    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        _show_dry_run(tier, data_dir, active_task_count, console)
        return

    # Confirmation prompt (skipped with -y)
    if not getattr(args, 'yes', False):
        if not _show_confirmation_prompt(tier, data_dir, active_task_count, console):
            console.print("[dim]Aborted.[/dim]")
            return

    # ── Execute reset ──
    tier_counts: dict[int, int] = {}
    total_freed: int = 0
    archive_path: Path | None = None

    for t in range(1, tier + 1):
        tier_def = RESET_TIERS[t]
        count = 0

        # Archive files first (ward_room.db at Tier 4)
        for fname in tier_def.get("archive_first", []):
            fpath = data_dir / fname
            if fpath.is_file():
                archive_dir = data_dir / "archives"
                archive_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                archive_path = archive_dir / f"{fpath.stem}_{timestamp}{fpath.suffix}"
                shutil.copy2(str(fpath), str(archive_path))

        # AD-541f: Record reset eviction before deleting files
        if t >= 2:
            _audit_db = data_dir / "eviction_audit.db"
            if _audit_db.is_file():
                try:
                    import sqlite3 as _sqlite3
                    import time as _time
                    import uuid as _uuid
                    _aconn = _sqlite3.connect(str(_audit_db))
                    _aconn.execute(
                        "INSERT INTO eviction_audit "
                        "(id, episode_id, agent_id, timestamp, reason, process, "
                        "details, content_hash, episode_timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (_uuid.uuid4().hex, "*", "*", _time.time(),
                         "reset", "probos_reset",
                         f"Tier {tier} reset — total episodic memory wipe",
                         "", 0.0),
                    )
                    _aconn.commit()
                    _aconn.close()
                except Exception:
                    pass  # Best-effort — reset must proceed

        # Delete files
        for fname in tier_def.get("files", []):
            fpath = data_dir / fname
            if fpath.is_file():
                total_freed += fpath.stat().st_size
                fpath.unlink()
                count += 1

        # Delete directories
        for dname in tier_def.get("dirs", []):
            dpath = data_dir / dname
            if dpath.is_dir():
                for fp in dpath.glob("*"):
                    if fp.is_file():
                        total_freed += fp.stat().st_size
                        fp.unlink()
                    elif fp.is_dir():
                        shutil.rmtree(fp, onerror=_force_remove_readonly)
                count += 1

        # Special cleanup
        for special in tier_def.get("special", []):
            if special == "chromadb_uuid_dirs":
                for uuid_dir in _find_chromadb_uuid_dirs(data_dir):
                    shutil.rmtree(uuid_dir, onerror=_force_remove_readonly)
                    count += 1
            elif special == "knowledge_subdirs":
                # Clear KnowledgeStore subdirectories (json/py files)
                for sub in _RESET_SUBDIRS:
                    sub_dir = repo_path / sub
                    if not sub_dir.is_dir():
                        continue
                    for fp in sub_dir.glob("*"):
                        if fp.is_file() and fp.suffix in (".json", ".py"):
                            fp.unlink()
                    count += 1
            elif special == "ontology_instance_id":
                instance_id_file = data_dir / "ontology" / "instance_id"
                if instance_id_file.is_file():
                    instance_id_file.unlink()
                    count += 1

        tier_counts[t] = count

    # Git commit if repo is git-initialized
    if (repo_path / ".git").is_dir():
        try:
            subprocess.run(
                ["git", "-C", str(repo_path), "add", "-A"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            subprocess.run(
                ["git", "-C", str(repo_path), "commit", "-m",
                 f"probos reset: Tier {tier} — {RESET_TIERS[tier]['name']}"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
        except Exception:
            pass  # Best-effort git commit during reset

    # ── Summary output ──
    tier_names = {1: "Reboot", 2: "Recommissioning", 3: "Maiden Voyage"}
    tier_labels_short = {1: "Runtime", 2: "Cognition+Identity", 3: "Knowledge"}

    console.print(f"\n[bold green]Reset complete — Tier {tier}: {tier_names[tier]}[/bold green]\n")

    for t in range(1, tier + 1):
        count = tier_counts.get(t, 0)
        console.print(f"  Tier {t} ({tier_labels_short[t]}):   {count} item(s) cleared")

    if total_freed > 0:
        if total_freed < 1024 * 1024:
            freed_str = f"{total_freed / 1024:.1f} KB"
        else:
            freed_str = f"{total_freed / (1024 * 1024):.1f} MB"
        console.print(f"  Space freed: {freed_str}")

    # Show preserved items
    preserved = []
    for t in range(tier + 1, 4):
        for fname in RESET_TIERS[t].get("files", []):
            preserved.append(fname)
        for dname in RESET_TIERS[t].get("dirs", []):
            preserved.append(dname + "/")
    preserved.append("archives/")
    console.print(f"\n  Preserved: {', '.join(preserved)}")

    if archive_path:
        console.print(f"\n  Ward Room archived to: {archive_path}")

    if active_task_count > 0:
        console.print(
            f"\n  [yellow]⚠ {active_task_count} scheduled task(s) active — "
            "routing may be degraded until Hebbian weights rebuild.[/yellow]"
        )


def _force_remove_readonly(func, path, exc_info):  # noqa: ARG001
    """Handle read-only git objects on Windows."""
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main() -> None:
    # Load .env file before anything reads env vars (AD-286)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

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
    serve_parser.add_argument("--discord", action="store_true", help="Also start Discord bot adapter")

    # --- probos reset ---
    reset_parser = subparsers.add_parser("reset", help="Clear learned state (tiered: --soft, default, --full)")
    reset_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    reset_parser.add_argument("--soft", action="store_true", help="Tier 1: Reboot — runtime transients only")
    reset_parser.add_argument("--full", action="store_true", help="Tier 3: Maiden Voyage — everything including records")
    reset_parser.add_argument("--dry-run", action="store_true", help="Show what would be cleared, do nothing")
    reset_parser.add_argument("--wipe-records", action="store_true", help="(deprecated, use --full)")
    reset_parser.add_argument("--config", "-c", type=Path, default=None, help="Path to config YAML")
    reset_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")

    args = parser.parse_args()

    # Windows ProactorEventLoop doesn't support add_reader required by pyzmq.
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if args.command == "init":
        _cmd_init(args)
        return

    if args.command == "reset":
        _cmd_reset(args)
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
                discord=args.discord,
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
