"""ProbOS entry point — boot runtime and launch interactive shell or API server.

Usage::

    probos                  # interactive shell (default)
    probos init             # create ~/.probos/ config
    probos setup            # configure an LLM provider (alias: probos model)
    probos serve            # HTTP + WebSocket API server
    probos serve --interactive  # API server + interactive shell
    probos --config config/node-1.yaml
"""

from __future__ import annotations

import os
os.environ["TQDM_DISABLE"] = "1"  # Suppress sentence-transformers progress bars

import argparse
import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

# BF-276 (2026-05-12): Windows + pipe-redirected stdout (e.g.
# ``probos serve --interactive | tee log.txt``) drops to cp1252 encoding by
# default and crashes the moment Rich tries to print a glyph like ✓ / ✗ / ⚠.
# Operators running diagnostic captures hit this twice before we added this
# guard. Force UTF-8 on both streams when piped — the standard library
# supports ``reconfigure(encoding=...)`` since Python 3.7. The native-terminal
# path (no redirection) already works because Rich detects the TTY and uses
# the Win32 console API directly. Idempotent — repeat invocations are no-ops.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            if _stream is not None and not _stream.isatty():
                _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            # Fall back silently — worst case the operator hits the cp1252
            # crash and has to set PYTHONIOENCODING=utf-8 manually (the
            # documented workaround in CONTRIBUTING.md / README).
            pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from probos import provider_setup
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient, _LLM_TIERS
from probos.cognitive.model_router import build_model_routing, ceiling_denials, routed_tiers
from probos.cognitive.verifier_independence import VerifierJudgePolicy, verifier_independence_report
from probos.config import load_config
from probos.execution.command_env import trusted_command_env
from probos.runtime import ProbOSRuntime
from probos.experience.shell import ProbOSShell

if TYPE_CHECKING:
    import httpx

    from probos.config import SystemConfig
    from datetime import datetime

    from probos.knowledge.archive_ledger import ArchiveLedger, SnapshotEntry
    from probos.knowledge.archive_promotion import PendingSource, PromotionReview
    from probos.knowledge.archive_store import ArchiveStore, GenerationRecord, PromotionRecord, SourceState
    from probos.knowledge.records_snapshot import SnapshotPlan
    from probos.knowledge.records_store import RecordsStore
    from probos.protocols import DatabaseConnection


def _default_data_dir() -> Path:
    """Return a stable, platform-appropriate data directory.

    Delegates to ``runtime._platform_data_dir()`` to ensure a single
    source of truth for the default data path (BF-265).
    """
    from probos.runtime import _platform_data_dir
    return _platform_data_dir()


def _probos_home() -> Path:
    """Return ~/.probos path."""
    return Path.home() / ".probos"


def _console_log_level(log_level: str, verbose: bool) -> int:
    """Resolve the console log handler level (AD-1026, DD-1).

    Default (``verbose=False``) keeps the console quiet at WARNING+ so the
    boot output surfaces only issues; ``verbose=True`` restores the
    configured level (the historical behavior) for the full INFO/DEBUG
    console stream. The rotating file handler always stays at INFO+
    regardless of this value.
    """
    if verbose:
        return getattr(logging, log_level.upper(), logging.INFO)
    return logging.WARNING


class _BootWarningCounter(logging.Handler):
    """Module-level handler tallying WARNING+ records during boot (AD-1026).

    Powers the end-of-boot health pointer (DD-4): after a quiet boot the
    operator still learns that *something* was logged and where the full
    detail lives. Counts WARNING and above only; INFO/DEBUG are ignored.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self.count += 1


_boot_warning_handler = _BootWarningCounter()


def _boot_warning_count() -> int:
    """Return WARNING+ records seen since the last ``_setup_logging`` call."""
    return _boot_warning_handler.count


def _setup_logging(log_level: str, verbose: bool = False) -> None:
    """Configure logging for shell mode — suppress noisy output.

    BF (2026-05-12): always write a rotating file log to the platform data
    dir. Captures all WARNING+ from probos.* and tier-status changes from
    cognitive subsystems regardless of how the operator launched the
    process. Removes the need for ``2>&1 | tee log.txt`` to capture
    diagnostic output, which on Windows + Git Bash + Ctrl+C makes the
    process unkillable from the launching terminal.
    """
    from logging.handlers import RotatingFileHandler
    _FMT = "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s"
    # BF-748: the console keeps the compact clock -- the operator is watching it
    # live and knows what day it is. The FILE gets the date, because it is an
    # archive that spans days and five rotations, and a bare HH:MM:SS makes every
    # forensic query ambiguous the moment it crosses midnight. Measured
    # 2026-08-11: a query anchored on "10:16" matched two different boots on two
    # different days and reported a working fix as still broken.
    formatter = logging.Formatter(_FMT, datefmt="%H:%M:%S")
    file_formatter = logging.Formatter(_FMT, datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.WARNING))
    # AD-1026 (DD-4): reset + attach the WARNING+ counter so the end-of-boot
    # health pointer reflects only this boot's notices.
    _boot_warning_handler.count = 0
    if _boot_warning_handler not in root.handlers:
        root.addHandler(_boot_warning_handler)
    # Console handler (stderr by default — Rich Console handles stdout).
    # AD-1026 (DD-1): quiet by default (WARNING+); --verbose restores the
    # configured level. The file handler below stays at INFO+ either way.
    _console_h = logging.StreamHandler()
    _console_h.setFormatter(formatter)
    _console_h.setLevel(_console_log_level(log_level, verbose))
    root.addHandler(_console_h)
    # File handler — best-effort; never block startup if the dir is missing.
    try:
        from probos.runtime import _platform_data_dir
        _log_dir = _platform_data_dir() / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _file_h = RotatingFileHandler(
            _log_dir / "probos.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,               # keep 5 rotations
            encoding="utf-8",
        )
        _file_h.setFormatter(file_formatter)
        # File log captures INFO+ regardless of console level so diagnostics
        # are always available without restarting with --log-level=INFO.
        _file_h.setLevel(logging.INFO)
        root.addHandler(_file_h)
    except Exception:
        # Best-effort — don't block boot on logging setup.
        pass
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

    # AD-754: redact PII/secrets in all root handlers.
    try:
        from probos.security.pii_redaction import apply_redaction_to_handlers

        apply_redaction_to_handlers(logging.getLogger().handlers)
    except Exception:
        # Redaction wiring must never block startup.
        pass


async def _ensure_ollama(config, console: Console) -> None:
    """Start Ollama if needed and warm up the model.

    1. Check if the Ollama server is reachable.
    2. If not, find and start ``ollama serve``, wait for readiness.
    3. Send a lightweight request to load the model into VRAM.
    """
    import httpx

    # Collect Ollama tier configs
    # BF-886 A-1: a warm-up is a generation request, so a text tier the model
    # routing cost ceiling leaves no model is not warmed up.
    denied = ceiling_denials(config)
    ollama_tiers: list[dict] = []
    for tier in _LLM_TIERS:
        tc = config.cognitive.tier_config(tier)
        if tc.get("api_format") == "ollama":
            if tier in denied:
                console.print(
                    f"  [dim]Not warming up the {tier} tier: the model routing "
                    "cost ceiling admits none of its models[/dim]"
                )
                continue
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
                env=trusted_command_env(),
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
    """Create an LLM client from config, falling back to MockLLMClient.

    BF-886 A-1: the model router, with its cost ceiling, is attached before the
    first probe -- a probe is a generation request -- so a text tier the
    ceiling leaves no model is not probed, is reported as excluded rather than
    unreachable, and never on its own selects MockLLMClient.
    """
    from rich.markup import escape

    cog = config.cognitive
    router = build_model_routing(config)
    denied = {} if router is None else router.denials(routed_tiers(cog))
    client = OpenAICompatibleClient(config=cog, rate_config=config.llm_rate, model_router=router)

    console.print("  Checking LLM endpoints...")
    connectivity = await client.check_connectivity()

    keys = provider_setup.configured_api_keys(cog)  # AD-1137 A-3: shown nowhere below, as in `probos doctor`
    for tier in _LLM_TIERS:
        tc = cog.tier_config(tier)
        # AD-742a: skip unconfigured optional tiers in the boot banner.
        if not tc.get("model"):
            continue
        reachable = connectivity.get(tier, False)
        where = escape(provider_setup.shown_base_url(tc["base_url"], keys))  # AD-1137 A-2: as `probos doctor` shows it
        if tier in denied:
            reason = escape(provider_setup.redact_keys(denied[tier], keys))
            console.print(f"  [yellow]\u2717[/yellow] LLM {tier}: not probed at {where}: {reason}")
            continue
        if reachable:
            model = escape(provider_setup.redact_keys(tc["model"], keys))
            console.print(f"  [green]\u2713[/green] LLM {tier}: {model} at {where}")
        else:
            console.print(f"  [yellow]\u2717[/yellow] LLM {tier}: {where} unreachable")

    # AD-1327: while the crew orchestrator is on (the crew verifier is built only then),
    # say whether the verifier judges with a model the crew also runs on.
    if config.agentic_dispatch.orchestrator_enabled:
        independence, detail = verifier_independence_report(VerifierJudgePolicy.from_cognitive(cog))
        shown = escape(provider_setup.redact_keys(f"Crew verifier: {detail}", keys))
        mark = "[green]\u2713[/green]" if independence == "independent" else "[yellow]\u26a0[/yellow]"
        console.print(f"  {mark} {shown}")

    # BF-886 A-1: a tier the cost ceiling excludes was not probed. Its exclusion
    # is a budget decision, not an outage, so it never selects the mock.
    if not any(connectivity.values()) and not denied:
        # All endpoints unreachable — fall back to mock
        await client.close()
        console.print(
            "  [yellow]\u26a0[/yellow] No LLM endpoints reachable. "
            "Falling back to [bold]MockLLMClient[/bold] "
            "(pattern-matched responses only)."
        )
        return MockLLMClient()

    # AD-1137 (#1414 F-f): as in the per-tier lines above (AD-742a), a tier without a model is
    # unconfigured, not unreachable, so the warning does not name it.
    down_tiers = [t for t, r in connectivity.items() if not r and cog.tier_config(t).get("model")]
    if down_tiers:
        console.print(
            f"  [yellow]\u26a0 Warning: {', '.join(down_tiers)} tier(s) unreachable[/yellow]"
        )

    return client


async def _check_nats(config, console: Console) -> None:
    """Check NATS server connectivity if enabled (AD-637).

    Uses raw TCP connect to verify NATS is listening. If unreachable on
    localhost and ``nats-server`` is on PATH, auto-start it (mirrors the
    ``_ensure_ollama`` pattern) so the operator no longer has to launch
    NATS manually before ProbOS. The NATS client library handles full
    protocol handshake during runtime startup.
    """
    if not config.nats.enabled:
        return

    import asyncio as _aio

    nats_url = config.nats.url
    # Extract host:port from nats://host:port
    host_port = nats_url.replace("nats://", "").replace("tls://", "")
    parts = host_port.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 4222

    async def _probe(timeout: float) -> bool:
        try:
            _, writer = await _aio.wait_for(
                _aio.open_connection(host, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return True
        except (OSError, _aio.TimeoutError):
            return False

    if await _probe(3.0):
        console.print(f"  [green]\u2713[/green] NATS: {nats_url}")
        return

    # Only attempt auto-start for local NATS instances.
    if host not in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        console.print(
            f"  [yellow]\u2717[/yellow] NATS: {nats_url} unreachable "
            "(remote host — will retry on startup)"
        )
        return

    nats_bin = shutil.which("nats-server")
    if not nats_bin:
        # Fall back to a bundled copy under the repo's tools/ directory so
        # operators don't have to put nats-server on PATH globally.
        exe = "nats-server.exe" if sys.platform == "win32" else "nats-server"
        project_root = Path(__file__).resolve().parent.parent.parent
        candidates = [
            project_root / "tools" / exe,
            _probos_home() / "tools" / exe,
        ]
        for candidate in candidates:
            if candidate.exists():
                nats_bin = str(candidate)
                break

    if not nats_bin:
        console.print(
            f"  [yellow]\u2717[/yellow] NATS: {nats_url} unreachable "
            "(nats-server not on PATH or in tools/ — install from "
            "https://docs.nats.io/running-a-nats-service/introduction/installation)"
        )
        return

    console.print("  [yellow]NATS is not running — starting it...[/yellow]")
    # JetStream is required by AD-637 (durable streams, attachment refs, etc.).
    jetstream_store = _default_data_dir() / "nats-jetstream"
    jetstream_store.mkdir(parents=True, exist_ok=True)
    cmd = [
        nats_bin,
        "-js",
        "-sd", str(jetstream_store),
        "-a", host if host != "localhost" else "127.0.0.1",
        "-p", str(port),
    ]
    try:
        subprocess.Popen(
            cmd,
            env=trusted_command_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        console.print(f"  [red]Failed to start nats-server: {exc}[/red]")
        return

    with console.status("  Waiting for NATS server..."):
        for _ in range(30):  # up to ~15 seconds
            await _aio.sleep(0.5)
            if await _probe(2.0):
                console.print(
                    f"  [green]\u2713[/green] NATS: {nats_url} (auto-started, JetStream at {jetstream_store})"
                )
                return

    console.print(
        f"  [yellow]\u26a0 nats-server launched but {nats_url} not reachable — continuing anyway[/yellow]"
    )


def _repo_default_config_path() -> Path:
    """Return the source checkout's ``config/system.yaml`` (outside the package in a wheel install)."""
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "config" / "system.yaml"


def _resolve_config_path(config_path: Path | None) -> Path:
    """Return the config file the shell and ``serve`` load: explicit, else ~/.probos, else project default."""
    if config_path is not None:
        return config_path

    # Try ~/.probos/config.yaml first
    home_config = _probos_home() / "config.yaml"
    if home_config.exists():
        return home_config

    # Fall back to project-bundled config
    return _repo_default_config_path()


def _load_config_with_fallback(config_path: Path | None) -> tuple:
    """Load config from the provided path, ~/.probos, or project default."""
    resolved = _resolve_config_path(config_path)
    return load_config(resolved), resolved


def _render_boot_summary(status: dict, verbose: bool) -> list[str]:
    """Render the pool-section boot lines (AD-1026, DD-2).

    Returns Rich-markup strings for the caller to print. ``verbose=True``
    reproduces the pre-AD-1026 per-pool detail (one line per pool, plus the
    red-team and a labelled Total line) byte-for-byte. The default collapsed
    view returns a single ``{total} agents across {N} pools`` summary plus the
    red-team line — but any pool below its target size still surfaces its own
    line so a degraded boot is never hidden behind the collapse.
    """
    pools: dict = status.get("pools", {})
    total_agents = status.get("total_agents", 0)
    red_team = status.get("consensus", {}).get("red_team_agents", 0)
    lines: list[str] = []

    def _pool_line(name: str, info: dict) -> str:
        return (
            f"  [green]\u2713[/green] Pool [bold]{name}[/bold]: "
            f"{info.get('current_size', 0)} {info.get('agent_type', '')} agents"
        )

    if verbose:
        for name, info in pools.items():
            lines.append(_pool_line(name, info))
    else:
        # DD-2: surface any pool that booted below its target size.
        for name, info in pools.items():
            if info.get("current_size", 0) < info.get("target_size", 0):
                lines.append(_pool_line(name, info))
        lines.append(
            f"  [green]\u2713[/green] {total_agents} agents across "
            f"{len(pools)} pools"
        )

    lines.append(
        f"  [green]\u2713[/green] Red team: {red_team} verification agents"
    )
    if verbose:
        lines.append(
            f"  [green]\u2713[/green] Total: {total_agents} agents across "
            f"{len(pools)} pools"
        )
    return lines


async def _boot_runtime(
    config_path: Path | None = None,
    fresh: bool = False,
    data_dir: Path | None = None,
    console: Console | None = None,
    verbose: bool = False,
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

    _setup_logging(config.system.log_level, verbose=verbose)

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

    # AD-637: Check NATS connectivity if enabled
    await _check_nats(config, console)

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
        agent_recall_threshold=config.memory.agent_recall_threshold,
        fts_keyword_floor=config.memory.fts_keyword_semantic_floor,
        query_reformulation_enabled=config.memory.query_reformulation_enabled,  # AD-584
        hnsw_sync_threshold=config.memory.hnsw_sync_threshold,  # AD-821
        hnsw_batch_size=config.memory.hnsw_batch_size,  # AD-821
        recall_rerank_enabled=config.memory.recall_rerank_enabled,  # AD-873
        recall_rerank_weights=config.memory.recall_rerank_weights,  # AD-873
        recall_confidence_weak_floor=config.memory.recall_confidence_weak_floor,  # AD-979a
        hybrid_recall_enabled=config.memory.hybrid_recall_enabled,  # AD-979c
        hybrid_rrf_k=config.memory.hybrid_rrf_k,  # AD-979c
        recall_fok_logging_enabled=config.memory.recall_fok_logging_enabled,  # AD-981a
        remember_know_typing_enabled=config.memory.remember_know_typing_enabled,  # AD-979f
        reconsolidation_enabled=config.memory.reconsolidation_enabled,  # AD-979e
        affect_capture_enabled=config.memory.affect_capture_enabled,  # AD-1037
        self_contradiction_recall_enabled=config.self_contradiction_recall.enabled,  # AD-1293 (#1200)
        eviction_disposition=config.memory.eviction_disposition,  # AD-1340
    )

    runtime = ProbOSRuntime(
        config=config, data_dir=str(data_path), llm_client=llm_client,
        episodic_memory=episodic_memory,
    )
    runtime._eviction_audit = eviction_audit  # AD-541f: expose for shutdown/SIF
    # AD-741: record the YAML path so the Settings panel can write back to it.
    runtime.config_path = str(resolved_path) if resolved_path else None

    # AD-731: wire the runtime's content-addressable AttachmentStore into the
    # LLM client so it can resolve attachment_ref source blocks to base64 just
    # before the HTTP POST. The LLM client is created before the runtime, so
    # we use the deferred setter rather than a constructor arg.
    if hasattr(llm_client, "set_attachment_store"):
        llm_client.set_attachment_store(runtime.attachment_store)

    # Boot sequence
    with console.status("  Initializing infrastructure..."):
        await runtime.start()

    # Show what was created (AD-1026, DD-2: collapsed by default; --verbose
    # restores the full per-pool detail).
    status = runtime.status()
    for _summary_line in _render_boot_summary(status, verbose):
        console.print(_summary_line)
    console.print()
    console.print("[bold green]ProbOS ready.[/bold green]")

    # AD-1026 (DD-4): when the quiet default boot logged any WARNING+, point
    # the operator at the full file log and the --verbose flag. Verbose mode
    # already printed the detail, so the pointer is suppressed there.
    _boot_notices = _boot_warning_count()
    if _boot_notices > 0 and not verbose:
        from probos.runtime import _platform_data_dir
        _boot_logfile = _platform_data_dir() / "logs" / "probos.log"
        console.print(
            f"[dim]\u26a0 {_boot_notices} notice(s) during boot \u2014 full log: "
            f"{_boot_logfile}; rerun with --verbose for detail.[/dim]"
        )

    return runtime, config, console


async def _boot_and_run(config_path: Path | None = None, fresh: bool = False, data_dir: Path | None = None, verbose: bool = False) -> None:
    """Boot runtime and launch interactive shell."""
    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, verbose=verbose)

    console.print(
        "[dim]Type /help for commands, or enter a natural language request.[/dim]"
    )
    console.print()

    # Interactive shell
    shell = ProbOSShell(runtime, console, self_mod_console_approval=True)
    try:
        await shell.run()
    finally:
        # BF-141: Write session record synchronously BEFORE async shutdown.
        # Ctrl+C cancels the task → CancelledError skips runtime.stop() →
        # session_last.json stays stale → inflated stasis on next boot.
        try:
            import json as _json
            import time as _time
            _sr = {
                "session_id": runtime._session_id,
                "start_time_utc": runtime._start_time_wall,
                "shutdown_time_utc": _time.time(),
                "uptime_seconds": _time.monotonic() - runtime._start_time,
                "agent_count": len(runtime.registry.all()),
                "reason": getattr(shell, '_quit_reason', '') or "interrupted",
            }
            (runtime._data_dir / "session_last.json").write_text(
                _json.dumps(_sr, indent=2)
            )
        except Exception:
            pass  # best-effort — don't block shutdown
        console.print("\n[bold red]ProbOS shutting down...[/bold red]")
        console.print("  [dim]Stopping runtime...[/dim]", end="")
        try:
            await asyncio.wait_for(runtime.stop(reason=getattr(shell, '_quit_reason', '')), timeout=10)
            console.print(" [green]done[/green]")
        except asyncio.TimeoutError:
            console.print(" [yellow]timed out (10s)[/yellow]")
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
    verbose: bool = False,
    force_unclean: bool = False,
) -> None:
    """Boot runtime and start the FastAPI/uvicorn server."""
    import uvicorn
    from probos.api import create_app

    console = Console()

    # AD-816: refuse to start when another ProbOS runtime owns the same
    # data directory. SQLite + ChromaDB single-writer assumptions break
    # when two instances share data/. Atomic O_EXCL create closes the
    # TOCTOU race: either we win the pidfile and own it, or we lose and
    # raise AnotherInstanceRunning. The acquired path is removed in the
    # cleanup finally block below.
    from probos.pidfile_guard import AnotherInstanceRunning, PidfileLockUnavailable, acquire_pidfile
    resolved_data_dir = data_dir or _default_data_dir()
    try:
        _pidfile = acquire_pidfile(resolved_data_dir)
    except (AnotherInstanceRunning, PidfileLockUnavailable) as exc:
        from rich.markup import escape  # AD-1341 S1 A7 (F4): the refusal names a path; it prints as text, never markup

        console.print(f"[red]✗[/red] {escape(str(exc))}", emoji=False)  # A7 (F4): serve's refusal
        raise SystemExit(2) from exc

    # AD-820: refuse to start when the previous shutdown left the data dir
    # in a known-bad state. Catches the failure mode that segfaulted the
    # runtime today (#750) and replaces a native segfault on next boot
    # with a graceful operator-readable refusal pointing at the recovery
    # command. --force-unclean overrides for legitimate recovery flows.
    from probos.shutdown_integrity import (
        UncleanShutdownDetected,
        check_previous_shutdown,
    )
    _is_first_boot = not (resolved_data_dir / "events.db").exists()
    try:
        check_previous_shutdown(
            resolved_data_dir,
            force_unclean=force_unclean,
            is_first_boot=_is_first_boot,
        )
    except UncleanShutdownDetected as exc:
        console.print(f"[red]✗[/red] {exc}")
        # Release the pidfile so a follow-up recovery boot isn't blocked
        # by our own stale marker.
        try:
            _pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(3) from exc

    # AD-822: probe ChromaDB in an isolated subprocess BEFORE the runtime
    # opens it. Catches the corruption-without-unclean-shutdown class of
    # failure that AD-820's marker misses (e.g. torn HNSW from a prior
    # process generation, sqlite page corruption from disk error). A
    # SIGSEGV inside the probe kills only the child; the parent observes
    # the non-zero exit code and refuses to boot with an actionable
    # remediation message pointing at AD-819. PROBOS_SKIP_EPISODIC_HEALTH_CHECK=1
    # bypasses the probe with a WARNING log.
    from probos.episodic_health import (
        EpisodicCorruptionDetected,
        check_episodic_health,
    )
    _health = check_episodic_health(resolved_data_dir)
    if not _health.ok:
        _exc = EpisodicCorruptionDetected(
            resolved_data_dir,
            _health.error or "unknown probe failure",
            _health.duration_s,
            file_validation_failed=_health.file_validation_failed,
        )
        console.print(f"[red]✗[/red] {_exc}")
        try:
            _pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(4) from _exc

    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console, verbose=verbose)

    if fresh:
        runtime._fresh_boot = True
        runtime._lifecycle_state = "reset"  # AD-502: --fresh flag = explicit reset

    app = create_app(runtime)

    # AD-708e: bound here so the cleanup `finally` can always reference it,
    # even if boot fails before the advertiser is built below.
    _advertiser = None

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

    # AD-472: Slack adapter (opt-in via uv extras)
    if config.channels.slack.enabled:
        from probos.channels.slack_adapter import SlackAdapter
        slack_cfg = config.channels.slack
        token = os.environ.get("PROBOS_SLACK_BOT_TOKEN", "") or slack_cfg.bot_token
        if token:
            slack_cfg = slack_cfg.model_copy(update={"bot_token": token})
            adapter = SlackAdapter(runtime, slack_cfg)
            await adapter.start()
            if getattr(adapter, "_started", False):
                adapters.append(adapter)
                console.print("  [green]\u2713[/green] Slack adapter started")
            else:
                console.print("  [red]\u2717[/red] Slack adapter failed — run: uv sync --extra slack")

    # AD-472: Webhook adapter (no opt-in extra; uses existing FastAPI)
    if config.channels.webhook.enabled:
        from probos.channels.webhook_adapter import WebhookAdapter
        webhook_cfg = config.channels.webhook
        secret = os.environ.get("PROBOS_WEBHOOK_SECRET", "") or webhook_cfg.shared_secret
        if secret:
            webhook_cfg = webhook_cfg.model_copy(update={"shared_secret": secret})
        adapter = WebhookAdapter(runtime, webhook_cfg)
        await adapter.start()
        if getattr(adapter, "_started", False):
            adapters.append(adapter)
            console.print("  [green]\u2713[/green] Webhook adapter started")

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

    # AD-708e: optionally advertise this server on the LAN via mDNS so a phone
    # can reach the HXI at a stable `.local` address. Default-OFF; NoOp when
    # disabled, the lib is absent, or bound to loopback. Never blocks boot.
    from probos.discovery import build_advertiser
    _advertiser = build_advertiser(getattr(config, "discovery", None), host, port)
    _advertising = await _advertiser.start()
    if _advertising:
        console.print(
            f"  [green]\u2713[/green] PADD discovery: "
            f"[bold]http://{config.discovery.hostname}.local:{port}[/bold]"
        )

    # Open HXI in browser (AD-260)
    import webbrowser
    webbrowser.open(f"http://{host}:{port}")

    console.print()

    # AD-816: pidfile is already owned by us (acquired atomically at the
    # top of _serve). The cleanup `finally` block below unlinks it on
    # shutdown. No re-write needed here; we used to refresh it after
    # boot but that was the regression that let a failing second-instance
    # attempt stomp the original's PID.

    # Heartbeat: log every 60s so silent process death shows up as
    # "log stopped" with a clear last-alive timestamp. Helps distinguish
    # internal os._exit (from /api/system/shutdown — see system.py) from
    # external TerminateProcess (Stop-Process / taskkill).
    _hb_logger = logging.getLogger("probos.heartbeat")
    async def _heartbeat_loop() -> None:
        import time as _t
        start = _t.monotonic()
        while True:
            try:
                await asyncio.sleep(60)
                uptime = int(_t.monotonic() - start)
                _hb_logger.info(
                    "runtime alive pid=%d uptime=%ds agents=%d",
                    os.getpid(), uptime, len(runtime.registry.all()),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                _hb_logger.exception("heartbeat loop iteration failed")
    heartbeat_task = asyncio.create_task(_heartbeat_loop(), name="serve-heartbeat")

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
        # Cancel heartbeat first so we stop emitting "alive" once shutdown begins.
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except BaseException:
            pass
        # AD-1341 S1 A6 (F1): the pidfile is no longer removed here, before anything has stopped: that told a reset
        # the data directory was free while the event log and the runtime's stores were still open. It goes after
        # runtime.stop() has returned (below).
        # AD-708e: stop the LAN mDNS advertiser (idempotent, never raises).
        if _advertiser is not None:
            try:
                await _advertiser.stop()
            except Exception:
                pass
        # BF-141: Write session record synchronously BEFORE async shutdown.
        try:
            import json as _json
            import time as _time
            _sr = {
                "session_id": runtime._session_id,
                "start_time_utc": runtime._start_time_wall,
                "shutdown_time_utc": _time.time(),
                "uptime_seconds": _time.monotonic() - runtime._start_time,
                "agent_count": len(runtime.registry.all()),
                "reason": "server_shutdown",
            }
            (runtime._data_dir / "session_last.json").write_text(
                _json.dumps(_sr, indent=2)
            )
        except Exception:
            pass
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
        runtime_closed = False
        try:
            await asyncio.wait_for(runtime.stop(), timeout=10)
            runtime_closed = True
            console.print(" [green]done[/green]")
        except asyncio.TimeoutError:
            console.print(" [yellow]timed out (10s)[/yellow]")
        except (KeyboardInterrupt, SystemExit):
            console.print(" [yellow]interrupted[/yellow]")
        except Exception as e:
            console.print(f" [yellow]warn: {e}[/yellow]")
        finally:
            console.print("[dim]ProbOS stopped.[/dim]")
            # AD-1341 S1 A6 (F1): the pidfile goes only now, once runtime.stop() has returned and its writers have
            # closed, and immediately before the process ends. A stop that timed out, failed or was interrupted may
            # leave a writer open, so the pidfile stays: the process ends at once, and the next acquirer finds a
            # dead PID and recovers it (AD-816).
            if runtime_closed:
                try:
                    _pidfile.unlink()
                except OSError:  # already gone, or not removable: the guard recovers a dead PID either way
                    pass
            os._exit(0)


def _detect_llm_providers(console: Console) -> dict[str, str]:
    """Probe known providers and return reachable endpoints.

    Returns a dict mapping provider name -> URL when reachable; empty otherwise.
    """
    import httpx

    detected: dict[str, str] = {}
    candidates = [
        ("ollama", "http://localhost:11434"),
        ("copilot-proxy", "http://127.0.0.1:8080"),
    ]
    for name, url in candidates:
        try:
            with httpx.Client(base_url=url, timeout=1.5) as client:
                # Ollama: GET /api/version. Copilot proxy: GET /v1/models.
                probe_path = "/api/version" if name == "ollama" else "/v1/models"
                resp = client.get(probe_path)
                if resp.status_code < 500:
                    detected[name] = url
        except Exception:
            continue

    if os.environ.get("ANTHROPIC_API_KEY"):
        # AD-484 rev (rec#3): respect ANTHROPIC_BASE_URL for compatible
        # endpoints; default to the canonical Anthropic API URL.
        anthropic_url = (
            os.environ.get("ANTHROPIC_BASE_URL")
            or "https://api.anthropic.com"
        )
        detected["anthropic"] = anthropic_url

    return detected


def _render_init_config(
    home: Path,
    *,
    llm_url: str,
    llm_model: str,
    api_format: str,
    profile: str,
    generated_by: str = "probos init",
) -> str:
    """Render the ``probos init`` config text; ``probos setup`` reuses it as its create-path scaffold."""
    config_content = f"""\
# ProbOS Configuration -- generated by `{generated_by}`
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
    # AD-711: claude-bootstrap-derived security profile (declarative; runtime
    # enforcement deferred to AD-711-1). The strict profile is the secure
    # default; relaxed is opt-in via ``--security-profile relaxed``.
    security_block_strict = """\
# AD-711: Security profile (claude-bootstrap-derived defaults)
# Generated with profile=strict. Edit ONLY by adding entries to ``allow``.
# Do NOT remove entries from ``deny`` without first reviewing the docs.
security:
  profile: "strict"
  permissions:
    allow:
      - "shell:pytest *"
      - "shell:git status *"
      - "shell:git diff *"
      - "shell:git log *"
    deny:
      - "shell:rm -rf *"
      - "shell:git push --force *"
      - "shell:git reset --hard *"
      - "fs:write:.env"
      - "fs:write:.env.*"
      - "fs:write:**/credentials.json"
"""
    security_block_relaxed = """\
# AD-711: Security profile (claude-bootstrap-derived defaults)
# Generated with profile=relaxed. THIS PROFILE IS WEAKER -- explicit opt-in only.
# To re-enable strict defaults, run: probos init --force --security-profile strict
security:
  profile: "relaxed"
  permissions:
    allow:
      - "shell:*"
    deny:
      - "shell:rm -rf /"
      - "fs:write:.env"
"""
    return config_content + (
        security_block_strict if profile == "strict" else security_block_relaxed
    )


def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``probos init`` -- interactive Rich TUI wizard (AD-484)."""
    from rich.prompt import Prompt

    console = Console()
    home = Path(args.probos_home) if args.probos_home else _probos_home()

    # AD-711: resolve security profile (default strict; invalid → strict).
    profile = getattr(args, "security_profile", "strict")
    if profile not in ("strict", "relaxed"):
        profile = "strict"

    if (home / "config.yaml").exists() and not args.force:
        console.print(
            f"[yellow]Config already exists at {home / 'config.yaml'}[/yellow]\n"
            f"Use [bold]--force[/bold] to overwrite."
        )
        return

    console.print(
        Panel.fit(
            "[bold blue]ProbOS Init[/bold blue]\n"
            "Setting up your ProbOS configuration.",
            border_style="blue",
        )
    )
    console.print()

    # Auto-detect providers
    console.print("  [dim]Detecting LLM providers...[/dim]")
    detected = _detect_llm_providers(console)
    for name, url in detected.items():
        console.print(f"  [green]\u2713[/green] {name}: {url}")
    if not detected:
        console.print("  [yellow]\u26a0[/yellow] No local LLM providers detected.")

    # Prompt for endpoint with detected default
    default_url = next(iter(detected.values()), "http://127.0.0.1:8080/v1")
    if default_url == "http://localhost:11434":
        default_url = "http://localhost:11434/v1"
    elif default_url == "http://127.0.0.1:8080":
        default_url = "http://127.0.0.1:8080/v1"
    llm_url = Prompt.ask("  LLM endpoint URL", default=default_url, console=console)

    # Prompt for model with sensible default per provider
    if "ollama" in detected or ":11434" in llm_url:
        default_model = "llama3.1:8b"
    else:
        default_model = "claude-sonnet-4-20250514"
    llm_model = Prompt.ask("  LLM model", default=default_model, console=console)

    api_format = "ollama" if ":11434" in llm_url else "openai"

    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    (home / "notes").mkdir(exist_ok=True)

    config_content = _render_init_config(
        home, llm_url=llm_url, llm_model=llm_model, api_format=api_format, profile=profile,
    )
    (home / "config.yaml").write_text(config_content, encoding="utf-8")

    console.print()
    console.print(f"  [green]\u2713[/green] Created [bold]{home}[/bold]")
    console.print(f"  [green]\u2713[/green] Config: [dim]{home / 'config.yaml'}[/dim]")
    console.print(f"  [green]\u2713[/green] Data dir: [dim]{home / 'data'}[/dim]")
    console.print()
    console.print(
        Panel.fit(
            "Run [bold]probos doctor[/bold] to verify your setup.\n"
            "Run [bold]probos[/bold] to start the interactive shell.",
            title="Next steps",
            border_style="green",
        )
    )


def _add_setup_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``probos setup`` and its alias ``probos model`` (AD-1135)."""
    setup_parser = subparsers.add_parser(
        "setup",
        aliases=["model"],
        help="Configure an OpenAI-compatible LLM provider for the text tiers",
    )
    setup_parser.add_argument(
        "--provider", choices=tuple(provider_setup.PRESETS), default=None, help="Provider preset",
    )
    setup_parser.add_argument(
        "--base-url", metavar="URL", default=None, help="OpenAI-compatible base URL, usually ending in /v1",
    )
    key_source = setup_parser.add_mutually_exclusive_group()
    key_source.add_argument(
        "--api-key-env", metavar="VAR", default=None, help="Read the API key from this environment variable",
    )
    key_source.add_argument(
        "--api-key", metavar="KEY", default=None,
        help="The API key itself; visible in shell history and the process list, so prefer --api-key-env",
    )
    setup_parser.add_argument("--model", metavar="NAME", default=None, help="Model for every text tier")
    for tier in provider_setup.TEXT_TIERS:
        setup_parser.add_argument(
            f"--model-{tier}", metavar="NAME", default=None, help=f"Model for the {tier} tier (overrides --model)",
        )
    setup_parser.add_argument(
        "--skip-validation", action="store_true", help="Write without contacting the provider",
    )
    setup_parser.add_argument(
        "--allow-insecure-http", action="store_true",
        help="Allow sending an API key over plain http:// to a non-loopback host",
    )
    setup_parser.add_argument(
        "--force", action="store_true",
        help="Rewrite the config when it cannot be edited in place (keeps every setting, drops comments)",
    )
    setup_parser.add_argument(
        "--yes", "-y", action="store_true", help="Never prompt; missing required input exits 1",
    )
    target = setup_parser.add_mutually_exclusive_group()
    target.add_argument(
        "--probos-home", metavar="DIR", default=None, help="Write DIR/config.yaml instead of ~/.probos/config.yaml",
    )
    # SUPPRESS: when absent here, a --config given before `setup` (the root parser's) is kept, not reset to None.
    target.add_argument(
        "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS, help="Edit or create this config file",
    )


def _setup_target(args: argparse.Namespace) -> Path:
    """AD-1135 Q1: ``--config PATH`` (before or after ``setup``), else ``config.yaml`` in ``--probos-home`` or ~/.probos."""
    config = getattr(args, "config", None)
    if config is not None:
        return Path(config)
    home = Path(args.probos_home) if args.probos_home else _probos_home()
    return home / "config.yaml"


def _setup_scaffold(home: Path) -> str:
    """Return ``probos init``'s config scaffold for setup's create path (AD-1135 B2).

    Init interpolates the home path raw into a double-quoted YAML string, where a
    double quote, a backslash or a non-printable character breaks the file or
    silently changes ``knowledge.repo_path``; raise SetupInputError (exit 2) instead.
    """
    # Provider values never enter the init template's raw f-string: it gets placeholders, the editor the values.
    scaffold = _render_init_config(
        home,
        llm_url="http://127.0.0.1:8080/v1",
        llm_model="unset",
        api_format="openai",
        profile="strict",
        generated_by="probos setup",
    )
    intended = (home / "knowledge").as_posix()
    try:
        knowledge = provider_setup.parse_config_text(scaffold).get("knowledge")
    except provider_setup.ConfigEditRefused:
        knowledge = None
    if not isinstance(knowledge, dict) or knowledge.get("repo_path") != intended:
        found = [
            name
            for name, present in (
                ("a double quote", '"' in intended),
                ("a backslash", "\\" in intended),
                ("a non-printable character", not intended.isprintable()),
            )
            if present
        ]
        raise provider_setup.SetupInputError(
            f"the config directory path contains {' and '.join(found) or 'characters'} that probos init's "
            "config template cannot carry; choose another directory"
        )
    return scaffold


# Caps the model suggestions at one screen; costs showing the rest of a long listing (OpenRouter lists hundreds).
_SETUP_SUGGESTIONS = 20


def _setup_preset(args: argparse.Namespace, console: Console) -> provider_setup.ProviderPreset | int:
    """Return the ``--provider`` preset, or ask for one defaulting to a detected local server (M4)."""
    from rich.markup import escape
    from rich.prompt import Prompt

    if args.provider is not None:
        return provider_setup.PRESETS[args.provider]
    if args.yes:
        console.print("[red]--provider is required.[/red]")
        return 1
    console.print("  [dim]Detecting local LLM providers...[/dim]")
    detected = _detect_llm_providers(console)
    # Only a local server with a preset picks the default; an ANTHROPIC_API_KEY has no preset.
    local = [name for name in ("ollama", "copilot-proxy") if name in detected]
    for name in local:
        console.print(f"  [green]\u2713[/green] {escape(name)} answers at {escape(detected[name])}")
    for preset in provider_setup.PRESETS.values():
        console.print(f"    {escape(preset.name)}: {escape(preset.label)}")
    name = Prompt.ask(
        "  Provider", choices=list(provider_setup.PRESETS), default=local[0] if local else "openai", console=console,
    )
    return provider_setup.PRESETS[name]


def _setup_api_key(
    args: argparse.Namespace, console: Console, preset: provider_setup.ProviderPreset,
) -> str | int:
    """Return the key from the flags, the preset's variable once confirmed, or a hidden prompt; never printed."""
    import getpass

    from rich.markup import escape
    from rich.prompt import Confirm

    if args.api_key_env:
        api_key = os.environ.get(args.api_key_env, "")
        if not api_key:
            console.print(f"[red]Environment variable {escape(args.api_key_env)} is not set or is empty.[/red]")
            return 1
        return api_key
    api_key = args.api_key or ""
    if args.api_key is None and not args.yes:
        key_env = preset.key_env
        if key_env and os.environ.get(key_env) and Confirm.ask(
            f"  Use the API key in the {escape(key_env)} environment variable?", default=True, console=console,
        ):
            return os.environ[key_env]
        if preset.requires_key or preset.name == "custom":
            hint = "input hidden" if preset.requires_key else "optional, input hidden"
            api_key = getpass.getpass(f"  API key ({hint}): ").strip()
    if preset.requires_key and not api_key:
        example = f", for example --api-key-env {preset.key_env}" if preset.key_env else ""
        console.print(
            f"[red]Provider {escape(preset.name)} needs an API key: "
            f"pass --api-key-env VAR or --api-key KEY{escape(example)}.[/red]"
        )
        return 1
    return api_key


def _setup_allow_insecure_http(args: argparse.Namespace, console: Console, base_url: str, api_key: str) -> bool | None:
    """Whether the key may go over plain http; interactive users are asked before any request (B5), None if not."""
    from rich.markup import escape
    from rich.prompt import Confirm

    if args.allow_insecure_http or args.yes or not provider_setup.sends_key_in_clear(base_url, api_key):
        return args.allow_insecure_http
    console.print(
        f"[yellow]{escape(base_url)} is plain http:// to a non-loopback host, "
        "so the API key would travel unencrypted.[/yellow]"
    )
    if Confirm.ask("  Send the API key over plain http anyway?", default=False, console=console):
        return True
    console.print("  Nothing was written.")
    return None


def _setup_listing(
    console: Console, base_url: str, api_key: str, transport: httpx.BaseTransport | None,
) -> provider_setup.ProbeResult | None:
    """Probe the model listing; return an OK or NOT_FOUND result, or print the failure and return None."""
    from rich.markup import escape

    outcome = provider_setup.ProbeOutcome
    console.print(f"  Checking {escape(base_url)} ...")
    listing = provider_setup.probe_models(base_url, api_key, transport=transport)
    if listing.outcome is outcome.NOT_FOUND:
        console.print(
            f"  [dim]No model listing at this base URL (HTTP {listing.status_code}); checking chat directly.[/dim]"
        )
        return listing
    if listing.outcome is outcome.OK:
        return listing
    console.print(f"[red]\u2717 Provider check failed:[/red] {escape(listing.message)}")
    if listing.outcome is outcome.BAD_RESPONSE:
        console.print(
            "  Hint: a web page may have answered instead of the API; "
            "OpenAI-compatible base URLs usually end in /v1."
        )
    return None


def _setup_models(
    args: argparse.Namespace,
    console: Console,
    preset: provider_setup.ProviderPreset,
    base_url: str,
    api_key: str,
    transport: httpx.BaseTransport | None,
) -> tuple[dict[str, str], provider_setup.ProbeResult | None] | int:
    """Resolve each text tier's model from the flags and preset, asking for the rest unless ``--yes`` (M4).

    Returns the models and the listing fetched to suggest one, if it was; or the exit code.
    """
    from rich.markup import escape
    from rich.prompt import Confirm, Prompt

    models = {
        tier: getattr(args, f"model_{tier}") or args.model or preset.models.get(tier) or ""
        for tier in provider_setup.TEXT_TIERS
    }
    gaps = [tier for tier, model in models.items() if not model]
    if not gaps:
        return models, None
    if args.yes:
        console.print(f"[red]A model is required: pass --model NAME (or --model-{gaps[0]} NAME).[/red]")
        return 1
    listing: provider_setup.ProbeResult | None = None
    if not args.skip_validation:
        listing = _setup_listing(console, base_url, api_key, transport)
        if listing is None:
            console.print("  Nothing was written.")
            return 3
    listed = listing.model_ids if listing is not None else ()
    if listing is not None and listed:
        # probe_models withheld every ID holding a form of the key; its message counts them (B8).
        console.print(f"  {escape(listing.message[:1].upper() + listing.message[1:])}:")
        for model_id in listed[:_SETUP_SUGGESTIONS]:
            console.print(f"    {escape(provider_setup.redact(model_id, api_key))}")
        if len(listed) > _SETUP_SUGGESTIONS:
            console.print(f"    ... and {len(listed) - _SETUP_SUGGESTIONS} more")
    if preset.name == "ollama" and listed:
        model = Prompt.ask("  Model", default=listed[0], console=console).strip()
    else:
        model = Prompt.ask("  Model", console=console).strip()
    if not model:
        console.print("[red]A model is required.[/red]")
        return 1
    try:
        # B9: before a per-tier question offers it back as its default.
        provider_setup.validate_holds_no_key(model, api_key, name=f"the model for the {gaps[0]} tier")
    except provider_setup.SetupInputError as exc:
        console.print(f"[red]Invalid setting:[/red] {escape(str(exc))}")
        return 2
    for tier in gaps:
        models[tier] = model
    if len(gaps) > 1 and Confirm.ask("  Use a different model for each tier?", default=False, console=console):
        for tier in gaps:
            models[tier] = Prompt.ask(f"  Model for the {tier} tier", default=model, console=console).strip()
    return models, listing


def _setup_choice(
    args: argparse.Namespace, console: Console, transport: httpx.BaseTransport | None,
) -> tuple[provider_setup.ProviderChoice, provider_setup.ProbeResult | None] | int:
    """Build the provider choice from the flags, asking for what they leave out unless ``--yes`` (M4).

    Returns the choice and any listing fetched to suggest a model, or prints why not and
    returns the exit code.
    """
    from rich.markup import escape
    from rich.prompt import Prompt

    preset = _setup_preset(args, console)
    if isinstance(preset, int):
        return preset
    raw_url = args.base_url or preset.base_url
    if not raw_url and not args.yes:
        raw_url = Prompt.ask("  Base URL (OpenAI-compatible, usually ending in /v1)", console=console).strip()
    if not raw_url:
        console.print(f"[red]--base-url is required for provider {escape(preset.name)}.[/red]")
        return 1
    try:
        base_url = provider_setup.normalize_base_url(raw_url)
    except provider_setup.SetupInputError as exc:
        console.print(f"[red]Invalid --base-url:[/red] {escape(str(exc))}")
        return 2
    api_key = _setup_api_key(args, console, preset)
    if isinstance(api_key, int):
        return api_key
    try:
        # B9: before the plain-http warning or the model listing shows the URL.
        provider_setup.validate_holds_no_key(base_url, api_key, name="the base URL")
    except provider_setup.SetupInputError as exc:
        console.print(f"[red]Invalid --base-url:[/red] {escape(str(exc))}")
        return 2
    allow_insecure_http = _setup_allow_insecure_http(args, console, base_url, api_key)
    if allow_insecure_http is None:
        return 1
    try:
        provider_setup.validate_key_transport(base_url, api_key, allow_insecure_http=allow_insecure_http)
    except provider_setup.SetupInputError as exc:
        console.print(f"[red]Invalid setting:[/red] {escape(str(exc))}")
        return 2
    resolved = _setup_models(args, console, preset, base_url, api_key, transport)
    if isinstance(resolved, int):
        return resolved
    models, listing = resolved
    choice = provider_setup.ProviderChoice(
        provider=preset.name, base_url=base_url, models=MappingProxyType(models), api_key=api_key,
    )
    try:
        provider_setup.validate_choice(choice, allow_insecure_http=allow_insecure_http)
    except provider_setup.SetupInputError as exc:
        console.print(f"[red]Invalid setting:[/red] {escape(str(exc))}")
        return 2
    return choice, listing


def _setup_validate(
    console: Console,
    choice: provider_setup.ProviderChoice,
    listing: provider_setup.ProbeResult,
    transport: httpx.BaseTransport | None,
) -> bool:
    """Probe each distinct model after an OK or NOT_FOUND listing; print the first failure and return False."""
    from rich.markup import escape

    outcome = provider_setup.ProbeOutcome
    for model in dict.fromkeys(choice.models.values()):
        result = provider_setup.probe_chat(
            choice.base_url, choice.api_key, model, model_ids=listing.model_ids, transport=transport,
        )
        if result.outcome is outcome.OK:
            console.print(f"  [green]\u2713[/green] {escape(result.message)}")
            continue
        if listing.outcome is outcome.NOT_FOUND and result.outcome is outcome.NOT_FOUND:
            console.print(
                "[red]\u2717 Provider check failed:[/red] no OpenAI-compatible API at this base URL; "
                "they usually end in /v1 (OpenRouter: /api/v1)."
            )
        else:
            console.print(f"[red]\u2717 Provider check failed:[/red] {escape(result.message)}")
        return False
    return True


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first.resolve())) == os.path.normcase(str(second.resolve()))


def _setup_candidate(
    args: argparse.Namespace,
    console: Console,
    target: Path,
    existing: str | None,
    values: dict[str, str],
) -> str | int:
    """Return the text setup would install (AD-1135 Q2), or print why not and return the exit code."""
    from rich.markup import escape

    try:
        scaffold = existing if existing is not None else _setup_scaffold(target.parent)
    except provider_setup.SetupInputError as exc:
        console.print(f"[red]Cannot create {escape(str(target))}:[/red] {escape(str(exc))}")
        return 2
    try:
        return provider_setup.apply_managed_values(scaffold, values)
    except provider_setup.ConfigEditRefused as exc:
        refusal = str(exc)
    if existing is None or not args.force:
        console.print(f"[red]Cannot edit {escape(str(target))}:[/red] {escape(refusal)}")
        if existing is not None:
            console.print("  Pass --force to rewrite it: every setting is kept, but its comments are not.")
        return 4
    try:
        candidate = provider_setup.rewrite_with_managed_values(
            existing,
            values,
            header="Rewritten by `probos setup --force`; the previous file, comments included, is its backup.",
        )
    except provider_setup.ConfigEditRefused as exc:
        console.print(f"[red]Cannot rewrite {escape(str(target))}:[/red] {escape(str(exc))}")
        return 4
    console.print(
        f"[yellow]--force: {escape(str(target))} will be rewritten[/yellow] ({escape(refusal)}); "
        "every setting is kept, its comments are not."
    )
    return candidate


def _setup_shadow_guard(args: argparse.Namespace, console: Console, target: Path) -> bool:
    """AD-1135 Q1: confirm before a new ~/.probos/config.yaml hides a checkout's config/system.yaml."""
    from rich.markup import escape
    from rich.prompt import Confirm

    current = _resolve_config_path(None)
    if target.exists() or not _same_path(target, _probos_home() / "config.yaml") or not current.exists():
        return True
    console.print(
        f"[yellow]Creating {escape(str(target))} changes the file probos and probos serve load:[/yellow] "
        f"they read {escape(str(current))} today and will read the new file instead, where settings "
        "it does not list fall back to their defaults."
    )
    if args.yes or Confirm.ask("  Create it anyway?", default=False, console=console):
        return True
    console.print("  Nothing was written.")
    return False


def _setup_shared_url_notes(console: Console, shared_url_tiers: dict[str, str], api_key: str) -> None:
    """Name each optional tier that kept the shared llm_base_url in place (AD-1135 B7), one line per tier."""
    from rich.markup import escape

    for tier, model in shared_url_tiers.items():
        shown = provider_setup.redact(model, api_key)  # read from the existing file, which can hold the key
        console.print(
            f"  Left the shared llm_base_url unchanged because {escape(tier)} (model {escape(repr(shown))}) uses it; "
            f"give {escape(tier)} its own llm_base_url_{escape(tier)} to move it"
        )


def _setup_report(
    console: Console,
    target: Path,
    existing: str | None,
    values: dict[str, str],
    backup: Path | None,
    *,
    api_key: str,
    shared_url_tiers: dict[str, str],
) -> None:
    """Print what setup wrote; of the key, only its presence is ever shown."""
    from rich.markup import escape

    verb = "Created" if existing is None else "Updated"
    console.print(f"[green]\u2713[/green] {verb} {escape(str(target))}")
    changed = provider_setup.changed_keys(existing, values)
    console.print(f"  Changed keys: {escape(', '.join(changed) or 'none')}")
    console.print(f"  API key: {'present' if api_key else 'not set'}")
    if backup is not None:
        console.print(f"  Backup: {escape(str(backup))}")
    _setup_shared_url_notes(console, shared_url_tiers, api_key)
    if api_key and _same_path(target, _repo_default_config_path()):
        console.print(
            "[yellow]This is the source checkout's tracked config/system.yaml: "
            "do not commit it with the API key.[/yellow]"
        )
    loaded = _resolve_config_path(None)
    if not _same_path(loaded, target):
        quoted = escape(f'"{target}"')
        console.print(
            f"probos and probos serve load {escape(str(loaded))}; to use this file, start them with "
            f"[bold]probos serve --config {quoted}[/bold] or [bold]probos --config {quoted}[/bold], "
            f"and check it with [bold]probos doctor --config {quoted}[/bold]."
        )
    else:  # AD-1137: doctor checks the file probos loads, which is this one
        console.print("Run [bold]probos doctor[/bold] to check the rest of the installation.")
    if os.environ.get("PROBOS_LLM_URL"):
        console.print(
            "[yellow]PROBOS_LLM_URL is set.[/yellow] It replaces only the shared llm_base_url, so the "
            "fast, standard and deep tiers configured here ignore it; tiers without their own endpoint use it."
        )
    console.print("Restart [bold]probos serve[/bold] (or the [bold]probos[/bold] shell) to use the new provider.")
    console.print(
        "[dim]Restart any running HXI before saving settings there: a settings save rewrites "
        "this file from the configuration it booted with.[/dim]"
    )


def _setup_confirm_write(
    console: Console, target: Path, choice: provider_setup.ProviderChoice, shared_url_tiers: dict[str, str],
) -> bool:
    """Show what would be written, the key only as present or not, and ask the final question (M4)."""
    from rich.markup import escape
    from rich.prompt import Confirm

    shown = {tier: provider_setup.redact(choice.models[tier], choice.api_key) for tier in provider_setup.TEXT_TIERS}
    models = ", ".join(f"{tier} {escape(model)}" for tier, model in shown.items())
    console.print(
        f"  Provider {escape(choice.provider)} at {escape(choice.base_url)}; models: {models}; "
        f"API key: {'present' if choice.api_key else 'not set'}."
    )
    _setup_shared_url_notes(console, shared_url_tiers, choice.api_key)
    if Confirm.ask(f"  Write {escape(str(target))}?", default=True, console=console):
        return True
    console.print("  Nothing was written.")
    return False


class _SetupPlan(NamedTuple):
    """What ``probos setup`` installs once every check and question has passed."""

    target: Path
    existing: str | None
    had_bom: bool
    choice: provider_setup.ProviderChoice
    values: dict[str, str]
    candidate: str
    kept: dict[str, provider_setup.TierEndpoint]
    shared_url_tiers: dict[str, str]


def _setup_plan(
    args: argparse.Namespace, console: Console, transport: httpx.BaseTransport | None,
) -> _SetupPlan | int:
    """Run AD-1135 section 3.4 steps 1-5 and, unless ``--yes``, the final question; return the plan or an exit code."""
    from rich.markup import escape

    if getattr(args, "config", None) is not None and args.probos_home:
        console.print(
            "[red]--config and --probos-home both choose the file setup writes; pass only one[/red] "
            "(a --config before setup counts too)."
        )
        return 2
    target = _setup_target(args)
    existing: str | None = None
    had_bom = False
    kept: dict[str, provider_setup.TierEndpoint] = {}
    if target.exists():
        try:
            existing, had_bom = provider_setup.read_config_text(target)
            # Not YAML, or optional-tier settings that do not load: exit 4 before anything else, --force included.
            kept = provider_setup.optional_tier_endpoints(existing)
        except provider_setup.ConfigEditRefused as exc:
            console.print(f"[red]Cannot edit {escape(str(target))}:[/red] {escape(str(exc))}")
            return 4

    chosen = _setup_choice(args, console, transport)
    if isinstance(chosen, int):
        return chosen
    choice, listing = chosen
    shared_url_tiers = provider_setup.tiers_using_shared_url(kept)  # B7: these keep the shared URL where it is
    values = provider_setup.managed_values(choice, retain_shared_url=bool(shared_url_tiers))
    candidate = _setup_candidate(args, console, target, existing, values)
    if isinstance(candidate, int):
        return candidate
    if not _setup_shadow_guard(args, console, target):
        return 1

    if args.skip_validation:
        console.print("  [yellow]Skipped the provider check (--skip-validation).[/yellow]")
    else:
        if listing is None:
            listing = _setup_listing(console, choice.base_url, choice.api_key, transport)
        if listing is None or not _setup_validate(console, choice, listing, transport):
            console.print("  Nothing was written.")
            return 3

    if candidate == existing:
        console.print(f"[green]\u2713[/green] {escape(str(target))} already uses this provider; nothing was written.")
        return 0
    if not args.yes and not _setup_confirm_write(console, target, choice, shared_url_tiers):
        return 1
    return _SetupPlan(target, existing, had_bom, choice, values, candidate, kept, shared_url_tiers)


def _cmd_setup(args: argparse.Namespace, *, transport: httpx.BaseTransport | None = None) -> int:
    """Handle ``probos setup`` / ``probos model`` (AD-1135): point the text tiers at one provider.

    Without ``--yes`` it asks for whatever the flags leave out; Ctrl+C or EOF before the
    write cancels with exit 1. ``transport`` is the probes' test seam; production passes None.
    """
    from rich.markup import escape

    console = Console(soft_wrap=True)  # never hard-wrap a path or URL mid-string (B4)
    try:
        plan = _setup_plan(args, console, transport)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled.[/yellow] Nothing was written.")
        return 1
    if isinstance(plan, int):
        return plan
    try:
        backup = provider_setup.write_config_atomic(
            plan.target,
            plan.candidate,
            had_bom=plan.had_bom,
            create=plan.existing is None,
            verify=lambda path: provider_setup.verify_config_file(path, plan.choice, kept=plan.kept),
        )
    except (provider_setup.ConfigEditRefused, OSError) as exc:
        key = plan.choice.api_key  # B9: the target path, and so an OSError that names it, can hold the key
        target = escape(provider_setup.redact(str(plan.target), key))
        console.print(f"[red]Could not write {target}:[/red] {escape(provider_setup.redact(str(exc), key))}")
        if isinstance(exc, provider_setup.ConfigReplaceFailed):
            backup = escape(provider_setup.redact(str(exc.backup), key))
            console.print(f"  It was not replaced; the backup taken first is kept at {backup}")
        return 4
    _setup_report(
        console,
        plan.target,
        plan.existing,
        plan.values,
        backup,
        api_key=plan.choice.api_key,
        shared_url_tiers=plan.shared_url_tiers,
    )
    return 0


def _cmd_qa_run_contracts(args: argparse.Namespace) -> int:
    """Handle ``probos qa run-contracts <path>`` (AD-713 / better-agents).

    Loads YAML behavior contracts from a file or directory and evaluates
    each against a stub invoker. Returns 0 only if every contract was
    measured and passed; 1 if any measured contract failed or any file
    failed to load; 2 if the path does not exist; 3 if nothing failed but
    something was not measured, an empty directory included.

    AD-1186 (#1123): the stub invoker raises, so no case is measured and
    each contract is inconclusive (BF-711). An empty reply is not the
    agent's answer, and an unwired runtime is not the agent's failure.
    AD-713-1 will swap the stub for a hot-runtime invoker.
    """
    import asyncio

    from rich.console import Console
    from rich.table import Table

    from probos.cognitive.behavior_contract import (
        evaluate_contract,
        load_contract,
    )

    console = Console()
    root = Path(args.path)
    if not root.exists():
        console.print(f"[red]Path not found: {root}[/red]")
        return 2
    files = sorted(root.glob("*.yaml")) if root.is_dir() else [root]
    if not files:
        console.print(f"[yellow]No contracts found at {root}[/yellow]")
        return 3  # AD-1186: an empty directory measured nothing

    async def _stub_invoker(agent_id: str, prompt: str) -> str:
        # AD-713-1 wires a real runtime invoker. Until then nothing is
        # measured (AD-1186, BF-711): raising records the case as unmeasured.
        raise RuntimeError("AD-713-1: no runtime invoker is wired")

    table = Table("Contract", "Score", "Result")
    failed = False
    unmeasured = False
    for f in files:
        try:
            contract = load_contract(f)
        except Exception as exc:
            console.print(f"[red]Failed to load {f.name}: {exc}[/red]")
            failed = True  # AD-1186: a contract that does not load is a failure
            continue
        result = asyncio.run(evaluate_contract(contract, _stub_invoker))
        score = "-" if result["inconclusive"] else f"{result['score']:.2f}"
        if result["inconclusive"]:
            # BF-711: an unmeasured contract neither passes nor fails.
            unmeasured = True
            verdict = "[yellow]not measured[/yellow]"
        elif result["passed"]:
            verdict = "[green]yes[/green]"
        else:
            failed = True
            verdict = "[red]no[/red]"
        table.add_row(contract.name, score, verdict)
    console.print(table)
    if failed:
        return 1
    return 3 if unmeasured else 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Handle ``probos doctor`` — pluggable check registry (AD-801).

    Delegates to ``probos.doctor.run_doctor``, which iterates every
    registered ``DoctorCheck``. AD-798 (sandbox), AD-803..807 (channel
    adapters), and AD-808 (migration) can register their own checks
    without editing this module.

    Builds the context here so the existing AD-484 monkey-patch points
    (`_probos_home`, `_default_data_dir` in this module) still work for
    tests.

    AD-1137: checks the config file ``probos`` and ``probos serve`` would
    load (``--config`` before or after ``doctor``, else ``_resolve_config_path``)
    and the data directory from ``--data-dir``, else the platform default.

    Returns the count of failed checks (0 = healthy, non-zero = issues).
    """
    from probos.doctor import run_doctor
    from probos.doctor.runner import build_context
    ctx = build_context(
        home_dir=_probos_home(),
        data_dir=getattr(args, "data_dir", None) or _default_data_dir(),
        config_path=_resolve_config_path(getattr(args, "config", None)),
    )
    # soft_wrap: a path or URL is never hard-wrapped mid-string, as in setup (AD-1135 B4).
    return asyncio.run(run_doctor(args, Console(soft_wrap=True), ctx=ctx))


def _cmd_crew_token(args: argparse.Namespace) -> int:
    """BF-908: ``probos crew-token set|rotate|clear|status``, the Captain's keyring action.

    Reads the config ``probos`` and ``probos serve`` would load (``--config`` before or
    after ``crew-token``, else ``_resolve_config_path``), as ``probos doctor`` does. The
    work is in ``probos/crew_token_cli.py``; only this module imports it.
    """
    from probos import crew_token_cli

    return crew_token_cli.run(
        args.crew_token_cmd,
        config_path=_resolve_config_path(getattr(args, "config", None)),
        use_stdin=bool(getattr(args, "stdin", False)),
        console=Console(soft_wrap=True),
    )


def _cmd_pairing(args: argparse.Namespace) -> int:
    """Handle ``probos pairing`` subcommands (AD-802).

    Operates directly on the SQLite store + a stub VO registry so the
    CLI works without booting the full runtime. Real runtime use goes
    through the wired ``runtime.pairing_service`` (see startup wiring).

    Returns 0 on success, non-zero on user-visible errors.
    """
    from probos.security.pairing import (
        PairingRegistry,
        PairingService,
        UnknownPairingCode,
    )
    from probos.visiting_officers import UnknownCapabilityError
    from rich.markup import escape  # BF-903 (A3): a refused name prints as text, never as markup

    console = Console()
    data_dir = _default_data_dir()
    db_path = data_dir / "pairings.db"

    sub = getattr(args, "pairing_cmd", None)

    # `pending` and `list` only need the SQLite store — no VO needed.
    if sub == "pending":
        registry = PairingRegistry(db_path)
        rows = registry.list_pending(channel=getattr(args, "channel", None))
        if not rows:
            console.print("[dim]No pending pairings.[/dim]")
            return 0
        for r in rows:
            console.print(
                f"  [yellow]{r.code}[/yellow]  channel=[bold]{r.channel}[/bold]  "
                f"raw_id={r.raw_id}  expires_at={r.expires_at:.0f}"
            )
        return 0

    if sub == "list":
        registry = PairingRegistry(db_path)
        rows = registry.list_paired(channel=getattr(args, "channel", None))
        if not rows:
            console.print("[dim]No active pairings.[/dim]")
            return 0
        for r in rows:
            console.print(
                f"  [green]{r.did}[/green]  channel=[bold]{r.channel}[/bold]  "
                f"raw_id={r.raw_id}  caps={','.join(r.capabilities)}  "
                f"expires_at={r.expires_at:.0f}"
            )
        return 0

    # `approve` and `revoke` need a VO registry — for CLI use without a
    # running runtime, we use a minimal stub that records sessions in
    # memory only (the next runtime boot will re-register via
    # restore_active_sessions). This keeps the CLI offline-usable.
    vo_stub = _OfflinePairingVOStub()
    service = PairingService(
        registry=PairingRegistry(db_path),
        visiting_officers=vo_stub,
    )

    if sub == "approve":
        caps_override: list[str] | None = None
        if getattr(args, "cap", None):
            caps_override = [c.strip() for c in args.cap.split(",") if c.strip()]
        ttl_s: float | None = None
        if getattr(args, "ttl_days", None) is not None:
            ttl_s = float(args.ttl_days) * 86400.0
        try:
            paired = asyncio.run(
                service.approve_pairing(
                    channel=args.channel,
                    code=args.code,
                    capabilities_override=caps_override,
                    session_ttl_seconds=ttl_s,
                ),
            )
        except (UnknownPairingCode, UnknownCapabilityError) as exc:  # BF-903: an undeclared --cap is refused with its name
            console.print(f"[red]Approve failed:[/red] {escape(str(exc))}", emoji=False)  # BF-903 (A3): a refused name prints as text
            return 1
        console.print(
            f"[green]Approved.[/green] did={paired.did} channel={paired.channel} "
            f"raw_id={paired.raw_id} caps={','.join(paired.capabilities)}"
        )
        return 0

    if sub == "revoke":
        removed = asyncio.run(service.revoke_pairing(args.did))
        if not removed:
            console.print(f"[yellow]No pairing found for did={args.did}[/yellow]")
            return 1
        console.print(f"[green]Revoked.[/green] did={args.did}")
        return 0

    console.print(f"[red]Unknown pairing subcommand: {sub!r}[/red]")
    return 2


class _OfflinePairingVOStub:
    """Minimal VisitingOfficerRegistry-shaped stub used by the CLI when
    no runtime is booted. Generates synthetic DIDs that survive in the
    SQLite store so a subsequent runtime boot can re-register them via
    ``PairingService.restore_active_sessions``.
    """

    def __init__(self) -> None:
        import uuid
        self._uuid = uuid
        self._sessions: dict = {}

    async def register(
        self,
        callsign: str,
        capabilities: list[str],
        *,
        origin: str = "",
        session_ttl_seconds: float | None = None,
    ):
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Session:
            did: str
            callsign: str

        did = f"did:probos:visiting:{self._uuid.uuid4().hex[:16]}"
        sess = _Session(did=did, callsign=callsign)
        self._sessions[did] = sess
        return sess

    def deregister(self, did: str) -> bool:
        return self._sessions.pop(did, None) is not None


def _cmd_verify_snapshot(args: argparse.Namespace) -> int:
    """Handle ``probos verify-snapshot`` (AD-1265 §7).

    Opens every file in a promoted snapshot through the normal connection
    path and checks it against the manifest. Writes nothing -- deliberately
    no AD-816 pidfile guard, because a read-only check must be runnable on a
    live vessel. That is the difference from restore (AD-1266).
    """
    import asyncio as _asyncio

    from probos.infrastructure.snapshot_verify import verify_snapshot

    console = Console()
    snapshot = Path(getattr(args, "snapshot", "") or "").expanduser()
    if not snapshot:
        console.print("[red]✗[/red] --snapshot is required")
        return 2

    report = _asyncio.run(verify_snapshot(snapshot.resolve()))
    console.print(report.render())
    if report.ok:
        console.print("[green]✓[/green] snapshot verified")
    else:
        console.print(
            "[red]✗[/red] snapshot did NOT verify; do not rely on it for recovery"
        )
    return report.exit_code


def _cmd_backup_reclaim(args: argparse.Namespace) -> int:
    """Handle ``probos backup-reclaim`` (AD-1296 §4).

    The operator's half of AD-1296 D3. The automatic sweep reclaims only what
    it can prove is finished -- a working directory naming this process's PID
    and a run id it is not writing -- and *keeps* everything else, because
    deleting on "unknown" was measured destroying a live peer's snapshot
    mid-copy. Retention cannot see a working directory either, so without this
    command "keep on unknown" would have no bound at all.

    The ``owner PID N is not running`` note is a **hint for a human, never an
    input to an automatic delete**. It is wrong across hosts (a PID from
    another machine is meaningless here) and wrong under PID recycling (a dead
    owner's number can be reissued to an unrelated live process). That is
    precisely why it informs the operator's judgement instead of driving the
    sweep's.

    Read-only listing takes no AD-816 pidfile guard, following
    ``verify-snapshot``. ``--force`` does: it deletes, and a live vessel may
    own one of the directories it is about to remove.
    """
    import time as _time

    from probos.infrastructure.backup import _WORKING_DIR_RE
    from probos.infrastructure.snapshot_manifest import INCOMPLETE_SUFFIX
    from probos.pidfile_guard import is_pid_alive

    console = Console()
    raw_root = getattr(args, "backup_root", "") or ""
    if not raw_root:
        console.print("[red]✗[/red] --backup-root is required")
        return 2
    backup_root = Path(raw_root).expanduser().resolve()
    if not backup_root.is_dir():
        console.print(f"[red]✗[/red] --backup-root is not a directory: {backup_root}")
        return 2

    force = bool(getattr(args, "force", False))
    if force:
        # AD-816: --force deletes, so it must refuse to run against a data dir
        # a live runtime owns. The listing path deliberately does not.
        from probos.pidfile_guard import (
            AnotherInstanceRunning,
            assert_no_other_instance,
        )

        data_dir = (getattr(args, "data_dir", None) or _default_data_dir()).resolve()
        try:
            assert_no_other_instance(data_dir)
        except AnotherInstanceRunning as exc:
            from rich.markup import escape  # AD-1341 S1 A7 (F4): the refusal names a path; it prints as text, never markup

            console.print(f"[red]✗[/red] {escape(str(exc))}", emoji=False)  # A7 (F4): backup-reclaim's refusal
            console.print(
                "[yellow]A running vessel may own one of these working "
                "directories. Stop it before using --force, or drop --force to "
                "list them read-only.[/yellow]"
            )
            return 2

    now = _time.time()
    orphans: list[tuple[Path, int, float, str]] = []
    for child in sorted(backup_root.iterdir(), key=lambda p: p.name):
        if not child.name.endswith(INCOMPLETE_SUFFIX) or not child.is_dir():
            continue
        size = sum(
            f.stat().st_size
            for f in child.rglob("*")
            if f.is_file()
        )
        try:
            age = now - child.stat().st_mtime
        except OSError:
            age = 0.0
        match = _WORKING_DIR_RE.match(child.name)
        if match is None:
            owner = "unparseable name (predates AD-1296, or not written by ProbOS)"
        else:
            pid = int(match.group(2))
            owner = f"PID {pid}, run {match.group(3)}"
            if pid == os.getpid():
                owner += " (this process)"
            elif not is_pid_alive(pid):
                owner += " -- hint: owner PID is not running (advisory only)"
        orphans.append((child, size, age, owner))

    if not orphans:
        console.print(f"[green]✓[/green] no working directories under {backup_root}")
        return 0

    total = sum(size for _c, size, _a, _o in orphans)
    console.print(
        f"[yellow]{len(orphans)}[/yellow] working director(ies) under "
        f"{backup_root}, {total} bytes total. Retention does not count these."
    )
    for child, size, age, owner in orphans:
        console.print(f"  {child.name}  {size} bytes  {age / 3600.0:.1f} h  {owner}")

    if not force:
        console.print(
            "[yellow]Nothing removed.[/yellow] Re-run with --force to delete "
            "them. The liveness notes above are hints, not proof of ownership: "
            "they are meaningless across hosts and can be wrong after PID reuse."
        )
        return 1

    removed = 0
    for child, _size, _age, _owner in orphans:
        try:
            shutil.rmtree(child)
        except OSError as exc:
            console.print(f"[red]✗[/red] could not remove {child}: {exc}")
            continue
        removed += 1
        console.print(f"[green]✓[/green] removed {child.name}")
    if removed != len(orphans):
        console.print(
            f"[red]✗[/red] removed {removed} of {len(orphans)}; the rest remain"
        )
        return 1
    return 0


def _cmd_rebuild_episodic(args: argparse.Namespace) -> int:
    """Handle ``probos rebuild-episodic`` (AD-819).

    Replays the surviving ward room into ChromaDB so agents regain
    semantic recall after a ChromaDB corruption + reset event (#750).
    Refuses to run when the runtime is using the same data dir.
    """
    import asyncio as _asyncio
    from datetime import datetime as _datetime
    from probos.maintenance.rebuild_episodic import (
        rebuild_from_wardroom,
        render_report,
    )
    from probos.pidfile_guard import (
        AnotherInstanceRunning,
        assert_no_other_instance,
    )

    console = Console()
    data_dir = (getattr(args, "data_dir", None) or _default_data_dir()).resolve()

    # AD-816 read-only check: refuse if the runtime currently owns the
    # data dir. We do NOT acquire the pidfile (the runtime may legitimately
    # need to keep running on a different dir); we only refuse on collision.
    try:
        assert_no_other_instance(data_dir)
    except AnotherInstanceRunning as exc:
        from rich.markup import escape  # AD-1341 S1 A7 (F4): the refusal names a path; it prints as text, never markup

        console.print(f"[red]✗[/red] {escape(str(exc))}", emoji=False)  # A7 (F4): rebuild-episodic's refusal
        console.print(
            "[yellow]Stop the runtime cleanly (Ctrl+C in the serve "
            "session or POST /api/system/shutdown) before running rebuild-episodic.[/yellow]"
        )
        return 2

    wardroom_db = data_dir / "ward_room.db"
    if not wardroom_db.exists():
        console.print(
            f"[red]✗[/red] ward_room.db not found at {wardroom_db}. "
            "Nothing to rebuild from."
        )
        return 3

    # --since parsing
    since_ts: float | None = None
    raw_since = getattr(args, "since", None)
    if raw_since:
        try:
            since_ts = _datetime.fromisoformat(raw_since).timestamp()
        except ValueError:
            console.print(
                f"[red]✗[/red] --since must be ISO date/datetime (got {raw_since!r})"
            )
            return 2

    dry_run = bool(getattr(args, "dry_run", False))

    async def _run() -> int:
        # In dry-run mode we use a no-op storer so we never touch ChromaDB.
        if dry_run:
            async def _noop_store(_kwargs: dict) -> None:
                return None

            report = await rebuild_from_wardroom(
                wardroom_db=wardroom_db,
                store_episode=_noop_store,
                since_ts=since_ts,
                dry_run=True,
            )
            console.print(render_report(report))
            return 0

        # Real rebuild: stand up an EpisodicMemory bound to the same
        # ChromaDB the runtime would use, then store synthesized
        # episodes through its public ``store(Episode)`` API so all the
        # gates fire normally (AD-610 storage gate, AD-607h security
        # gate, content-hash computation, etc.).
        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode

        cfg, _cfg_path = _load_config_with_fallback(getattr(args, "config", None))
        em = EpisodicMemory(
            db_path=str(data_dir / "episodic.db"),
            max_episodes=cfg.memory.max_episodes,
            relevance_threshold=cfg.memory.relevance_threshold,
            verify_content_hash=cfg.memory.verify_content_hash,
            query_reformulation_enabled=cfg.memory.query_reformulation_enabled,
            hnsw_sync_threshold=cfg.memory.hnsw_sync_threshold,  # AD-821
            hnsw_batch_size=cfg.memory.hnsw_batch_size,  # AD-821
            eviction_disposition=cfg.memory.eviction_disposition,  # AD-1340
        )
        await em.start()

        try:
            # Snapshot existing episode ids so re-runs are fast-skip.
            existing_ids: set[str] = set()
            try:
                if em._collection:
                    result = em._collection.get(include=[])
                    for ep_id in (result or {}).get("ids", []) or []:
                        existing_ids.add(ep_id)
            except Exception:
                # Fall through with empty set — store_episode will be
                # idempotent via stable ids + content hash anyway.
                pass

            async def _store(kwargs: dict) -> None:
                await em.store(Episode(**kwargs))

            report = await rebuild_from_wardroom(
                wardroom_db=wardroom_db,
                store_episode=_store,
                existing_episode_ids=existing_ids,
                since_ts=since_ts,
                dry_run=False,
            )
        finally:
            await em.stop()

        console.print(render_report(report))

        # BF-288: a successful rebuild IS the recovery signal. Reset the
        # AD-820 marker so the next `probos serve` is not blocked by the
        # `consolidation_result=failed` left over from the crash that
        # forced the rebuild. On failure (errors present), leave the
        # marker untouched so the operator still sees AD-820's warning.
        if not report.errors and report.episodes_written > 0:
            try:
                from probos.shutdown_integrity import mark_clean_shutdown
                mark_clean_shutdown(
                    data_dir,
                    consolidation_result="rebuilt",
                    note=(
                        f"AD-819 rebuild from {report.source}: "
                        f"{report.episodes_written} episodes written"
                    ),
                )
                console.print(
                    "[green]✓[/green] AD-820 shutdown marker reset "
                    "(consolidation_result=rebuilt)"
                )
            except Exception:
                # Marker write failure is non-fatal — operator can re-run
                # or delete the marker manually. Log via Console so the
                # signal isn't lost in the rebuild summary.
                console.print(
                    "[yellow]![/yellow] Could not reset shutdown_status.json "
                    "(rebuild itself succeeded; you may need to delete "
                    "the marker manually before the next boot)."
                )

        return 0 if not report.errors else 1

    return _asyncio.run(_run())


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Handle ``probos migrate <openclaw|hermes> ...`` (AD-808)."""
    from probos.migration import (
        execute_plan,
        plan_migration,
        render_text_report,
    )

    console = Console()
    source = getattr(args, "migrate_source", None)
    if source not in ("openclaw", "hermes"):
        console.print("[red]Unknown migration source[/red]")
        return 2
    report = plan_migration(
        source,
        source_dir=getattr(args, "source_dir", None),
        preset=getattr(args, "preset", "user-data"),
        overwrite=getattr(args, "overwrite", False),
    )
    if report.errors:
        for err in report.errors:
            console.print(f"[red]{err}[/red]")
        return 1
    execute_plan(report, dry_run=getattr(args, "dry_run", False))
    console.print(render_text_report(report))
    return 0


def _cmd_channel(args: argparse.Namespace) -> int:
    """Handle ``probos channel ...`` subcommands (AD-803a+).

    Currently routes the ``telegram setup`` flow; AD-804..807 (Slack /
    Teams / Matrix / Discord refresh) plug in here.
    """
    console = Console()
    sub = getattr(args, "channel_cmd", None)
    if sub == "telegram":
        tg_sub = getattr(args, "channel_tg_cmd", None)
        if tg_sub == "setup":
            return _cmd_channel_telegram_setup(args, console)
        console.print(f"[red]Unknown telegram subcommand: {tg_sub!r}[/red]")
        return 2
    if sub == "slack":
        sl_sub = getattr(args, "channel_sl_cmd", None)
        if sl_sub == "setup":
            return _cmd_channel_slack_setup(args, console)
        console.print(f"[red]Unknown slack subcommand: {sl_sub!r}[/red]")
        return 2
    if sub == "matrix":
        mx_sub = getattr(args, "channel_mx_cmd", None)
        if mx_sub == "setup":
            return _cmd_channel_matrix_setup(args, console)
        console.print(f"[red]Unknown matrix subcommand: {mx_sub!r}[/red]")
        return 2
    console.print(f"[red]Unknown channel subcommand: {sub!r}[/red]")
    return 2


def _cmd_channel_telegram_setup(args: argparse.Namespace, console: Console) -> int:
    """AD-803a: interactive Telegram bot setup.

    Validates the token via ``getMe`` and persists the config to
    ``~/.probos/channels/telegram.yaml`` (mode 0600 on POSIX).
    """
    import getpass
    import os

    import yaml as _yaml

    from probos.channels.telegram_client import TelegramAPIError, TelegramClient

    token = getattr(args, "token", None)
    if not token:
        console.print(
            "[bold blue]Telegram setup[/bold blue] — "
            "Get a bot token from @BotFather first."
        )
        try:
            token = getpass.getpass("Bot token (input hidden): ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1
    if not token:
        console.print("[red]No token provided.[/red]")
        return 1

    async def _validate(t: str) -> dict | None:
        client = TelegramClient(token=t, timeout=10.0)
        try:
            return await client.get_me()
        except TelegramAPIError as exc:
            console.print(f"[red]getMe failed:[/red] {exc}")
            return None
        finally:
            await client.close()

    me = asyncio.run(_validate(token))
    if me is None:
        return 1
    username = me.get("username", "<unknown>") if isinstance(me, dict) else "<unknown>"
    console.print(f"[green]\u2713[/green] Token validated as @{username}")

    home = _probos_home()
    channels_dir = home / "channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = channels_dir / "telegram.yaml"
    payload = {
        "enabled": True,
        "token": token,
        "polling_timeout_s": 25,
        "allowed_updates": ["message"],
    }
    cfg_path.write_text(_yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    # Secret hygiene on POSIX. Windows ACL handling is out of scope —
    # the file lives under the operator's home directory and inherits
    # the parent ACL by default.
    if os.name != "nt":
        try:
            os.chmod(cfg_path, 0o600)
        except OSError:
            console.print(f"[yellow]Could not chmod {cfg_path} to 0600 — check perms manually.[/yellow]")
    console.print(f"[green]Wrote[/green] {cfg_path}")
    console.print("Run [bold]probos doctor[/bold] to verify, then restart [bold]probos serve[/bold] to activate.")
    return 0


def _cmd_channel_slack_setup(args: argparse.Namespace, console: Console) -> int:
    """AD-804: interactive Slack bot setup.

    Validates the xoxb-… token via ``auth.test`` and persists the
    config to ``~/.probos/channels/slack.yaml`` (mode 0600 on POSIX).
    """
    import getpass
    import os

    import yaml as _yaml

    from probos.channels.slack_client import SlackAPIError, SlackClient

    token = getattr(args, "token", None)
    if not token:
        console.print(
            "[bold blue]Slack setup[/bold blue] — "
            "Create a Slack app, install it to your workspace, copy the "
            "Bot User OAuth Token (xoxb-…) from the OAuth & Permissions page."
        )
        try:
            token = getpass.getpass("Bot token (input hidden): ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1
    if not token:
        console.print("[red]No token provided.[/red]")
        return 1

    async def _validate(t: str) -> dict | None:
        client = SlackClient(bot_token=t, timeout=10.0)
        try:
            return await client.auth_test()
        except SlackAPIError as exc:
            console.print(f"[red]auth.test failed:[/red] {exc}")
            return None
        finally:
            await client.close()

    identity = asyncio.run(_validate(token))
    if identity is None:
        return 1
    user_id = identity.get("user_id", "<unknown>") if isinstance(identity, dict) else "<unknown>"
    team = identity.get("team", "<unknown>") if isinstance(identity, dict) else "<unknown>"
    console.print(f"[green]\u2713[/green] Token validated — bot user_id={user_id} team={team}")

    home = _probos_home()
    channels_dir = home / "channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = channels_dir / "slack.yaml"
    payload = {
        "enabled": True,
        "bot_token": token,
        "channels": [],
        "poll_interval_s": 8.0,
        "poll_inbound": True,
        "default_thread_ts": True,
    }
    cfg_path.write_text(_yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(cfg_path, 0o600)
        except OSError:
            console.print(f"[yellow]Could not chmod {cfg_path} to 0600 — check perms manually.[/yellow]")
    console.print(f"[green]Wrote[/green] {cfg_path}")
    console.print("Run [bold]probos doctor[/bold] to verify, then restart [bold]probos serve[/bold] to activate.")
    return 0


def _cmd_channel_matrix_setup(args: argparse.Namespace, console: Console) -> int:
    """AD-806: interactive Matrix bot setup.

    Exchanges a password for a long-lived access token via /login,
    persists token + homeserver to ``~/.probos/channels/matrix.yaml``
    (mode 0600 on POSIX). Password is NOT persisted.
    """
    import getpass
    import os

    import yaml as _yaml

    from probos.channels.matrix_client import MatrixAPIError, MatrixClient

    homeserver = (getattr(args, "homeserver", None) or "").strip()
    user_id = (getattr(args, "user_id", None) or "").strip()
    password = getattr(args, "password", None) or ""

    if not homeserver:
        console.print(
            "[bold blue]Matrix setup[/bold blue] — Enter your homeserver URL "
            "(e.g. https://matrix.org or https://your-homeserver.example.com)."
        )
        try:
            homeserver = input("Homeserver URL: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1
    if not user_id:
        console.print("Enter your full Matrix ID, e.g. @yeo:matrix.org")
        try:
            user_id = input("User ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1
    if not password:
        try:
            password = getpass.getpass("Password (input hidden): ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1

    if not (homeserver and user_id and password):
        console.print("[red]homeserver, user_id, and password are all required.[/red]")
        return 1

    async def _login(hs: str, uid: str, pw: str) -> str | None:
        client = MatrixClient(homeserver=hs, timeout=10.0)
        try:
            return await client.login_password(uid, pw)
        except MatrixAPIError as exc:
            console.print(f"[red]login failed:[/red] {exc}")
            return None
        finally:
            await client.close()

    token = asyncio.run(_login(homeserver, user_id, password))
    if not token:
        return 1
    console.print(f"[green]\u2713[/green] Login succeeded for {user_id}")

    home = _probos_home()
    channels_dir = home / "channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = channels_dir / "matrix.yaml"
    payload = {
        "enabled": True,
        "homeserver": homeserver,
        "user_id": user_id,
        "access_token": token,
        "auto_join_invites": True,
        "sync_timeout_ms": 25000,
    }
    cfg_path.write_text(_yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(cfg_path, 0o600)
        except OSError:
            console.print(f"[yellow]Could not chmod {cfg_path} to 0600 — check perms manually.[/yellow]")
    console.print(f"[green]Wrote[/green] {cfg_path}")
    console.print("Run [bold]probos doctor[/bold] to verify, then restart [bold]probos serve[/bold] to activate.")
    return 0


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
            # AD-1340: archived episodes are nurture; a new crew must not inherit them
            "episode_archive.db",
            # BF-902: the per-episode indexes go with the episodes they index (chroma.sqlite3 above)
            "episode_fts.db", "participant_index.db", "activation_tracker.db",
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
        "episode_archive.db": "Episode archive",
        "episode_fts.db": "Episode keyword index",
        "participant_index.db": "Episode participant index",
        "activation_tracker.db": "Episode activation log",
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


#: AD-1341 S6: the data directory's nature, which only --clean-slate clears (the procedure store, ``runtime.py``).
_NATURE_DIR = "procedures"


def _nature_rows(table: Table, data_dir: Path, clean_slate: bool) -> None:
    """AD-1341 S6: what ``--clean-slate`` clears, as the confirmation and the dry run show it."""
    if clean_slate:
        table.add_row("\n[bold]Nature (--clean-slate)[/bold]", "", "")
        table.add_row(
            f"  • {_NATURE_DIR}/", "Cognitive JIT procedures, their challengers and index",
            _get_file_size(data_dir / _NATURE_DIR),
        )


def _nature_preserved(clean_slate: bool) -> list[tuple[str, str, str]]:
    """AD-1341 S6: nature kept (without ``--clean-slate``) and the skill catalog, which no reset touches."""
    kept = [] if clean_slate else [(f"{_NATURE_DIR}/", "Cognitive JIT procedures: nature, kept by design", "")]
    return [*kept, ("config/skills/", "Skill catalog: part of the installation, never cleared", "")]


def _show_confirmation_prompt(
    tier: int, data_dir: Path, active_task_count: int, console: Console, *, clean_slate: bool = False,
) -> bool:
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
    _nature_rows(table, data_dir, clean_slate)  # AD-1341 S6: the confirmation names what a clean slate clears

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
    preserved_items += _nature_preserved(clean_slate)  # AD-1341 S6: the confirmation names nature kept

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


def _show_dry_run(
    tier: int, data_dir: Path, active_task_count: int, console: Console, *, clean_slate: bool = False,
) -> None:
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
    _nature_rows(table, data_dir, clean_slate)  # AD-1341 S6: the dry run names what a clean slate clears

    preserved_items = []
    for t in range(tier + 1, 4):
        for fname in RESET_TIERS[t].get("files", []):
            fpath = data_dir / fname
            preserved_items.append((fname, _file_purpose(fname), _get_file_size(fpath)))
        for dname in RESET_TIERS[t].get("dirs", []):
            preserved_items.append((dname + "/", _file_purpose(dname), ""))
    preserved_items.append(("archives/", "Ward Room backups", ""))
    preserved_items += _nature_preserved(clean_slate)  # AD-1341 S6: the dry run names nature kept

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


def _cmd_reset(args: argparse.Namespace) -> int:
    """Handle ``probos reset`` — tiered reset system (BF-070). Returns the exit code (AD-1341 S1).

    0 done, declined or a dry run; 1 refused with nothing deleted (a vessel owns the data directory, the Ship's
    Archive lies inside what the reset deletes, or the promotion of a tier 2 or 3 reset failed; AD-1341 S6: or its
    snapshot, or a ``--clean-slate`` that could not be recorded or finished, or the generation's close, before the
    tier loop; AD-1341 S6 A2: or a refusal its preflight knows before anything is written); 2 a
    ``--skip-promotion`` without a usable reason, or a ``--clean-slate`` with ``--soft`` or a disabled archive.
    At tier 2 and above what the crew published is promoted into the Ship's Archive before the tier loop.
    """
    console = Console()

    # Deprecated flag notice
    if getattr(args, 'wipe_records', False):
        console.print("[yellow]⚠ --wipe-records is deprecated, use --full[/yellow]")

    # Resolve the effective tier (from the flags alone; it needs no configuration)
    tier = _resolve_tier(args)

    # AD-1341 S1: --skip-promotion REASON is checked before anything is read, locked or deleted, and (A4, F4)
    # before the configuration is loaded, so a malformed configuration cannot turn exit 2 into a traceback.
    skip_reason = getattr(args, 'skip_promotion', None)
    if skip_reason is not None:
        problem = _skip_promotion_problem(skip_reason, tier)
        if problem:
            console.print(f"[red]✗[/red] {problem}")
            return 2
    clean_slate = bool(getattr(args, 'clean_slate', False))  # AD-1341 S6: the Captain's opt-in reset of nature
    if clean_slate and tier < 2:  # AD-1341 S6: --soft keeps the crew, so there is no new crew to start clean
        console.print("[red]✗[/red] --clean-slate applies to a reset of tier 2 or above; --soft keeps the crew.")
        return 2

    # Load config to find knowledge repo_path
    config, _ = _load_config_with_fallback(getattr(args, 'config', None))
    repo_path = Path(config.knowledge.repo_path).expanduser() if config.knowledge.repo_path else Path.home() / ".probos" / "knowledge"
    data_dir = getattr(args, 'data_dir', None) or _default_data_dir()
    data_dir = Path(data_dir)

    # Use data_dir-based knowledge path if the config path doesn't exist
    data_dir_knowledge = data_dir / "knowledge"
    if not repo_path.is_dir() and data_dir_knowledge.is_dir():
        repo_path = data_dir_knowledge

    if clean_slate and not config.archive.enabled:  # AD-1341 S6: a clean slate is never unrecorded
        console.print(
            "[red]✗[/red] --clean-slate records what it clears in the Ship's Archive, which is disabled "
            "(archive.enabled). Nothing was changed."
        )
        return 2

    # AD-1341 S1 A4 (F3): refuse a reset that would delete the Ship's Archive. Every tier and a dry run too, before
    # the scheduled-task read, the confirmation and the pidfile; nothing is opened or touched.
    overlap = _archive_reset_overlap(config, tier, data_dir, repo_path, clean_slate=clean_slate)  # AD-1341 S6 A2
    if overlap:
        console.print("[red]✗[/red] probos reset refused: the Ship's Archive is inside what this reset deletes.")
        console.print(
            f"  archive.db_path, or the snapshots directory beside it, is inside or around {overlap}; move it out of "
            "what a reset deletes. Nothing was changed.",  # AD-1341 S6 A2: the snapshots are protected too
            markup=False,
        )
        return 1

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

    # AD-1341 S6 A2: every refusal that can be known before anything is written, shared by the dry run and the reset
    refusal = _reset_preflight(config, tier, data_dir, skip_reason, clean_slate=clean_slate)

    # --dry-run: show what would happen and exit
    if getattr(args, 'dry_run', False):
        if refusal:  # AD-1341 S6 A4: a reset that would refuse does nothing, so its dry run reads nothing more
            console.print("  [yellow]⚠ This reset would refuse, writing and deleting nothing:[/yellow]")
            console.print(f"    {refusal}", markup=False, emoji=False)
            console.print("\n  [dim][DRY RUN] No changes made.[/dim]")
            return 0  # AD-1341 S6 A4 (R2-B1, C-R2-F1): no tier table, plan or description reads the refused path
        _show_dry_run(tier, data_dir, active_task_count, console, clean_slate=clean_slate)
        if tier >= 2:  # AD-1341 S1: the promotion plan; reads Ship's Records, opens no archive, takes no pidfile
            return _show_promotion_plan(config, data_dir, skip_reason, console, tier=tier)
        return 0
    if refusal:  # AD-1341 S6 A2: before the confirmation, the pidfile and the promotion, so nothing is written
        console.print("[red]✗[/red] probos reset refused before writing anything:")
        console.print(f"  {refusal}", markup=False, emoji=False)
        return 1

    # Confirmation prompt (skipped with -y)
    if not getattr(args, 'yes', False):
        if not _show_confirmation_prompt(tier, data_dir, active_task_count, console, clean_slate=clean_slate):
            console.print("[dim]Aborted.[/dim]")
            return 0

    # AD-1341 S1 (D12): every executing reset holds the AD-816 pidfile `probos serve` takes for this data directory,
    # so no vessel writes beside the reset or boots into it half done. A live owner refuses it.
    from rich.markup import escape

    from probos.pidfile_guard import AnotherInstanceRunning, PidfileLockUnavailable, acquire_pidfile

    try:
        reset_pidfile = acquire_pidfile(data_dir)
    except AnotherInstanceRunning as exc:
        console.print(f"[red]✗[/red] {escape(str(exc))}", emoji=False)
        console.print("[yellow]probos reset refused: stop the vessel first. Nothing was changed.[/yellow]")
        return 1
    except PidfileLockUnavailable as exc:  # A6 (F2): no vessel to stop; this filesystem cannot lock
        console.print(f"[red]✗[/red] {escape(str(exc))}", emoji=False)
        console.print("[yellow]probos reset refused: file locks unavailable. Nothing was changed.[/yellow]")
        return 1
    try:
        # AD-1341 S1: what the crew published is promoted before anything is deleted; any failure refuses.
        promote_first = tier >= 2  # AD-1341 S1: tier 1 keeps the crew, so it has nothing to promote
        promoted, closing = (  # AD-1341 S6 A2 (C-F3): the generation's close is recorded last, below
            _promote_before_reset(config, tier, data_dir, skip_reason, console) if promote_first else (True, None)
        )
        if not promoted:
            console.print("[red]✗[/red] probos reset refused before deleting anything.")
            return 1  # AD-1341 S1: refused before the tier loop; nothing was deleted
        # AD-1341 S6: --clean-slate clears nature after the promotion (which described it) and before the tier loop, so
        # a failure here leaves every crew file in place and the same command finishes it.
        if clean_slate and not _clear_nature(config, tier, data_dir, console):
            console.print("[red]✗[/red] probos reset refused before its tier loop; the crew's files are untouched.")
            return 1
        # AD-1341 S6 A2 (C-F3): the generation is closed only once everything before the tier loop has succeeded
        if closing is not None and not _close_generation(config, closing, console):
            console.print("[red]✗[/red] probos reset refused before its tier loop; run the same command again.")
            return 1

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
                    env=trusted_command_env(),
                    capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                )
                subprocess.run(
                    ["git", "-C", str(repo_path), "commit", "-m",
                     f"probos reset: Tier {tier} — {RESET_TIERS[tier]['name']}"],
                    env=trusted_command_env(),
                    capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                )
            except Exception:
                pass  # Best-effort git commit during reset
    finally:
        # AD-1341 S1: released on every exit. Left behind, it names a finished PID, which the next acquire removes.
        try:
            reset_pidfile.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            console.print(
                f"[yellow]⚠ The pidfile {escape(str(reset_pidfile))} was not removed: {escape(str(exc))}[/yellow]"
            )

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
    if clean_slate:  # AD-1341 S6
        console.print("  Nature cleared (--clean-slate): procedures/ (Cognitive JIT procedures)")
    else:
        console.print("  Nature kept: procedures/ (Cognitive JIT procedures)")
    console.print("  The skill catalog (config/skills) is part of the installation; no reset touches it.")

    if archive_path:
        console.print(f"\n  Ward Room archived to: {archive_path}")

    if active_task_count > 0:
        console.print(
            f"\n  [yellow]⚠ {active_task_count} scheduled task(s) active — "
            "routing may be degraded until Hebbian weights rebuild.[/yellow]"
        )
    return 0


# ── AD-1341 S1: the Ship's Archive before a reset, and the Captain's erasure ──

#: Shown, never written: what a plan is attributed to when the ship has no instance id. A promotion needs one.
_UNATTRIBUTED_TIMELINE = "(no instance id)"


def _skip_promotion_problem(reason: str, tier: int) -> str:
    """Why ``--skip-promotion REASON`` cannot be used, or ``""``. Checked before anything is read or locked."""
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    if tier < 2:
        return "--skip-promotion applies to a reset of tier 2 or above; --soft promotes nothing."
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        return f"--skip-promotion needs a reason of 1 to {ARCHIVE_REASON_MAX_CHARS} characters."
    return ""


def _read_instance_id(data_dir: Path) -> str:
    """The ship's instance id (``ontology/instance_id``, stripped), or ``""`` when there is none.

    The generation a reset closes is attributed to it, and tier 2 deletes the file, so a reset reads it before
    the tier loop. It is the file the ontology loader writes on a vessel's first boot.
    """
    id_file = data_dir / "ontology" / "instance_id"
    if not id_file.is_file():
        return ""
    return id_file.read_text(encoding="utf-8").strip()


def _reset_records_store(config: SystemConfig, data_dir: Path) -> RecordsStore:
    """Ship's Records at the path this vessel writes (D10's resolver), never initialised: reading needs no git."""
    from probos.config import resolve_records_repo_path
    from probos.knowledge.records_store import RecordsStore

    records_path = resolve_records_repo_path(config.records, data_dir)
    return RecordsStore(config.records.model_copy(update={"repo_path": str(records_path)}), ontology=None)


def _configured_archive_store(config: SystemConfig) -> ArchiveStore:
    """The Ship's Archive at the path startup opens (AD-1265's resolver), not yet initialised.

    Only the computed default's directory is created, as startup does; an operator's path is used as given.
    """
    from probos.config import resolve_archive_db_path
    from probos.knowledge.archive_store import ArchiveStore
    from probos.storage.sqlite_factory import default_factory

    archive_path = resolve_archive_db_path(config.archive)
    if not config.archive.db_path:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveStore(str(archive_path), connection_factory=default_factory)


def _archive_reset_overlap(
    config: SystemConfig, tier: int, data_dir: Path, repo_path: Path, *, clean_slate: bool = False,
) -> str:
    """What a reset of ``tier`` deletes that is, or holds, the Ship's Archive or its snapshots; ``""`` when nothing.

    S1 A4 (F3): the targets are what the tier loop removes for tiers 1 to ``tier``: each listed file; each listed
    directory, whose contents go; ChromaDB's UUID-named directories; the knowledge store's subdirectories (only their
    ``.json`` and ``.py`` files go, but an archive there is refused too); and the instance id file. AD-1341 S6 A2
    (A-F2): the snapshots directory beside the archive is protected at every tier too, in both directions (inside or
    equal to a target, or a target inside it). Every side is resolved (symlinks, junctions, ``..``) and compared with
    the platform's case rule, so no link or junction aliases one into another. It reads paths only and opens nothing.
    """
    from probos.config import resolve_archive_db_path

    if not config.archive.enabled:  # D13: the reset neither opens nor protects a disabled archive
        return ""
    archive = os.path.normcase(str(resolve_archive_db_path(config.archive).resolve()))
    snapshots = os.path.normcase(str(_snapshots_dir(config).resolve()))  # AD-1341 S6 A2: the snapshots too
    targets: list[Path] = []
    for level in range(1, tier + 1):
        tier_def = RESET_TIERS[level]
        specials = tier_def.get("special", [])
        targets += [data_dir / name for name in [*tier_def.get("files", []), *tier_def.get("dirs", [])]]
        if "chromadb_uuid_dirs" in specials:
            targets += _find_chromadb_uuid_dirs(data_dir)
        if "knowledge_subdirs" in specials:
            targets += [repo_path / sub for sub in _RESET_SUBDIRS]
        if "ontology_instance_id" in specials:
            targets.append(data_dir / "ontology" / "instance_id")
    if clean_slate:  # AD-1341 S6 A2: --clean-slate deletes the procedure store's directory too (C-F1)
        targets.append(data_dir / _NATURE_DIR)
    for target in targets:
        resolved = os.path.normcase(str(target.resolve()))
        within = resolved.rstrip(os.sep) + os.sep
        if archive == resolved or archive.startswith(within):
            return str(target)
        if snapshots == resolved or snapshots.startswith(within) or resolved.startswith(snapshots + os.sep):
            return str(target)  # AD-1341 S6 A2: a reset never deletes a snapshot, nor a directory that holds one
    return ""


def _promote_before_reset(
    config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None, console: Console,
) -> tuple[bool, GenerationRecord | None]:
    """Promote what the crew published into the Ship's Archive before a reset of tier 2 or above.

    (True, the generation's close) when the reset may go on; (False, None), having said why, when it must not, with
    nothing deleted. AD-1341 S6 A2 (C-F3): the close is returned, not recorded: ``_cmd_reset`` records it with
    ``_close_generation`` once any clean slate has finished, so no generation is closed while its crew's files
    remain; None when there is nothing to close. With the archive disabled there is nowhere to promote to: a notice,
    and (True, None) (D13). That check comes before the one ``asyncio.run``, so a caller already inside an event loop
    with the archive disabled (``tests/test_bf902_fts_reconciliation.py``) never starts a second loop.
    """
    from rich.markup import escape

    if not config.archive.enabled:
        console.print(
            "[yellow]⚠ The Ship's Archive is disabled (archive.enabled): "
            "nothing is promoted before this reset.[/yellow]"
        )
        return True, None
    try:
        timeline_id = _read_instance_id(data_dir)  # before the tier loop deletes it
        proceed, message, closing = asyncio.run(
            _promote_into_archive(config, tier, data_dir, timeline_id, skip_reason)
        )
    except Exception as exc:  # any failure refuses the reset, and the Captain sees why
        console.print(
            f"[red]✗[/red] Ship's Archive promotion failed: {escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return False, None  # AD-1341 S1: a failed promotion refuses the reset
    console.print(f"  {escape(message)}" if proceed else f"[red]✗[/red] {escape(message)}")
    return proceed, closing if proceed else None


async def _promote_into_archive(
    config: SystemConfig, tier: int, data_dir: Path, timeline_id: str, skip_reason: str | None,
) -> tuple[bool, str, GenerationRecord | None]:
    """The promotion run, or the skip: (the reset may go on, what to tell the Captain, the generation's close).

    Raises on any failure, and closes the archive on every exit. Without an instance id nothing can be
    attributed (D9): anything to promote refuses, and a directory with nothing to promote has no generation to
    record, so nothing is opened. AD-1341 S6 A2 (C-F3): the close (promoted or skipped) is returned, never recorded
    here: ``_cmd_reset`` records it with ``_close_generation`` once any clean slate has finished.
    """
    from probos.knowledge.archive_promotion import plan_promotion, promote_ship_records
    from probos.knowledge.archive_store import GenerationOutcome, GenerationRecord

    records = _reset_records_store(config, data_dir)
    if skip_reason is None and not timeline_id:
        plan = await plan_promotion(records, timeline_id=_UNATTRIBUTED_TIMELINE)
        if plan.records:  # AD-1341 S1: nothing can be attributed without an instance id
            return False, (
                f"No instance id: {len(plan.records)} record(s) cannot be attributed to a timeline. "
                "Pass --skip-promotion REASON to reset without promoting them."
            ), None
        return True, "No instance id and nothing to promote: no generation is recorded.", None
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        if skip_reason is not None:
            skipped = GenerationRecord(
                timeline_id=timeline_id, reset_tier=tier, outcome=GenerationOutcome.SKIPPED, reason=skip_reason,
            )
            also = " The Ship's Records snapshot is skipped with it." if tier >= 3 else ""  # AD-1341 S6
            message = (  # AD-1341 S6 A4 (C-R2-F2): printed before the clearance and the close, so "will be"
                f"Ship's Archive promotion skipped; the reason will be recorded with the generation's close: "
                f"{skip_reason.strip()}{also}"
            )
            return True, message, skipped  # AD-1341 S6 A2 (C-F3): _close_generation records it, after any clean slate
        promoted = await promote_ship_records(records, archive, timeline_id=timeline_id)
        nature = await _nature_record(data_dir, timeline_id)  # AD-1341 S6 A2: read before the snapshot
        notes: list[str] = []
        if tier >= 3:  # AD-1341 S6: what a --full reset deletes from Ship's Records is kept first, as one checked file
            notes.append(await _snapshot_ship_records(config, data_dir, timeline_id))
        notes.insert(0, await _describe_nature(archive, nature))  # AD-1341 S6 A2: archived after the snapshot (B-F2)
        closed = GenerationRecord(
            timeline_id=timeline_id, reset_tier=tier, outcome=GenerationOutcome.PROMOTED,
            created=len(promoted.created), present=len(promoted.present), erased=len(promoted.erased),
            withheld=len(promoted.withheld),
        )  # AD-1341 S6 A2 (C-F3): returned; _close_generation records it after any clean slate
    finally:
        await archive.close()
    message = (
        f"Ship's Archive: {len(promoted.created)} promoted, {len(promoted.present)} already archived, "
        f"{len(promoted.erased)} erased by the Captain, {len(promoted.vetoed)} vetoed by the Captain, "
        f"{len(promoted.withheld)} withheld (timeline {timeline_id})."
    ) + "".join(f"\n  {note}" for note in notes)
    return True, message, closed


async def _open_read_only(path: str) -> DatabaseConnection:
    """AD-1341 S6: open a database the reset only reads, through SQLite's ``mode=ro`` (BF-906): never created."""
    from probos.storage.sqlite_factory import default_factory

    return await default_factory.connect(path, read_only=True)


async def _nature_record(data_dir: Path, timeline_id: str) -> PromotionRecord | None:
    """AD-1341 S6: this generation's nature description, built one way for the reset, the dry run, pending and veto."""
    from probos.knowledge.nature_description import PROCEDURES_DB, nature_description_record

    started = _generation_started(data_dir)
    if started is None or not timeline_id:
        return None
    return await nature_description_record(
        data_dir / PROCEDURES_DB, _open_read_only, timeline_id=timeline_id, started=started,
    )


async def _describe_nature(archive: ArchiveStore, record: PromotionRecord | None) -> str:
    """AD-1341 S6: archive this generation's nature description before the reset; say what became of it.

    A2 (B-F2): the promotion reads ``record`` before the snapshot (an unreadable store refuses there) and archives it
    here, after the snapshot, so a snapshot that fails leaves no description to duplicate on the retry.
    """
    from probos.knowledge.archive_promotion import promote_nature_description

    if record is None:
        return "Nature description: this generation developed no Cognitive JIT procedure, so there is none."
    outcome = await promote_nature_description(archive, record)
    return f"Nature description {record.source_ref}: {outcome.value}."


async def _pending_nature(config: SystemConfig, data_dir: Path) -> PendingSource | None:
    """AD-1341 S6: the nature description the next reset would archive, with what promoting it now would do."""
    from probos.knowledge.archive_promotion import review_nature_description

    record = await _nature_record(data_dir, _read_instance_id(data_dir))
    if record is None:
        return None
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        return await review_nature_description(archive, record)  # S3's census: only archive_promotion names source_state
    finally:
        await archive.close()


#: AD-1341 S6: the Ship's Records directory a tier 3 reset deletes (``RESET_TIERS[3]["dirs"]``), so the one it keeps.
_SNAPSHOT_SOURCE = "ship-records"


def _generation_started(data_dir: Path) -> datetime | None:
    """AD-1341 S6: when this ship's generation began: the modification time (UTC) of ``ontology/instance_id``, which
    the ontology loader writes once, at the ship's first boot. None when there is no instance id."""
    from datetime import UTC, datetime

    id_file = data_dir / "ontology" / "instance_id"
    if not id_file.is_file():
        return None
    return datetime.fromtimestamp(id_file.stat().st_mtime, UTC)


def _snapshots_dir(config: SystemConfig) -> Path:
    """AD-1341 S6: where Ship's Records snapshots are kept: beside the Ship's Archive's database (AD-1265's resolver)."""
    from probos.config import resolve_archive_db_path
    from probos.knowledge.records_snapshot import SNAPSHOT_DIR_NAME

    return resolve_archive_db_path(config.archive).parent / SNAPSHOT_DIR_NAME


def _snapshot_plan(data_dir: Path) -> SnapshotPlan:
    """AD-1341 S6: what a snapshot of the Ship's Records a tier 3 reset deletes would hold. Opens no file."""
    from probos.knowledge.records_snapshot import plan_snapshot

    return plan_snapshot(data_dir / _SNAPSHOT_SOURCE)


def _reset_preflight(
    config: SystemConfig, tier: int, data_dir: Path, skip_reason: str | None, *, clean_slate: bool = False,
) -> str:
    """AD-1341 S6 A2: why this reset must refuse, known before anything is written; ``""`` when nothing does.

    ``_cmd_reset`` runs it before the confirmation, the pidfile and the promotion, and its dry run shows it, so a reset
    it refuses has promoted, described, snapshotted, recorded and closed nothing. At tier 3, with the archive enabled
    and no ``--skip-promotion``: the Ship's Records snapshot's plan (the root and every entry: a link, a special file,
    the bounds, a path that cannot be inspected), the instance id that keys it, and its destination (no link or
    junction at the snapshots directory or the timeline's). Reads the instance id, names and sizes; opens no
    database. The snapshot checks again where it writes (register R28).
    """
    from probos.knowledge.records_snapshot import SnapshotRefused, is_link_or_junction, snapshot_relative_path

    if clean_slate:  # AD-1341 S6 A2: before the promotion reads the procedure store through it (B-F3, C-F2)
        problem = _nature_dir_problem(data_dir)
        if problem:
            return problem
    if tier < 3 or not config.archive.enabled or skip_reason is not None:
        return ""
    try:
        plan = _snapshot_plan(data_dir)
        if not plan.files:
            return ""
        timeline_id, started = _read_instance_id(data_dir), _generation_started(data_dir)
        if not timeline_id or started is None:  # AD-1341 S6: no ship to key the snapshot by
            return (
                f"No instance id: Ship's Records hold {len(plan.files)} file(s) a --full reset would delete with no "
                "ship to key their snapshot by. Pass --skip-promotion REASON to reset without promoting or snapshotting."
            )
        snapshot_relative_path(timeline_id, started, started)  # an instance id that cannot name a directory refuses
        for directory in (_snapshots_dir(config), _snapshots_dir(config) / timeline_id):
            if is_link_or_junction(directory):  # AD-1341 S6 A2: a snapshot is never written through a link
                return f"{directory} is a link or junction; a snapshot is written only into the snapshots directory."
    except (SnapshotRefused, OSError, ValueError) as exc:
        return f"The Ship's Records snapshot would refuse this reset: {exc}"
    return ""


def _configured_ledger(config: SystemConfig) -> ArchiveLedger:
    """AD-1341 S6: the reset's ledger in the Ship's Archive's file (the path startup opens), not yet initialised."""
    from probos.config import resolve_archive_db_path
    from probos.knowledge.archive_ledger import ArchiveLedger
    from probos.storage.sqlite_factory import default_factory

    return ArchiveLedger(str(resolve_archive_db_path(config.archive)), connection_factory=default_factory)


async def _open_ledger(config: SystemConfig) -> ArchiveLedger:
    """AD-1341 S6: the ledger, once the Ship's Archive itself has been opened (so brought to its schema) and closed."""
    archive = _configured_archive_store(config)
    await archive.initialize()
    await archive.close()
    ledger = _configured_ledger(config)
    await ledger.initialize()
    return ledger


async def _records_listing(config: SystemConfig, root: Path) -> frozenset[str]:
    """AD-1341 S6: the paths Ship's Records' own listing returns under ``root``, as the promotion's listing reads them."""
    from probos.knowledge.records_store import RecordsStore

    store = RecordsStore(config.records.model_copy(update={"repo_path": str(root)}), ontology=None)
    return frozenset(entry["path"] for entry in await store.list_entries())


async def _snapshot_ship_records(config: SystemConfig, data_dir: Path, timeline_id: str) -> str:
    """AD-1341 S6: keep what a ``--full`` reset deletes from Ship's Records as one checked snapshot; say what was kept.

    Written and checked under a temporary name, recorded in the archive's ledger, then published. Any failure removes
    the temporary file and propagates, so the reset refuses with nothing deleted. The Markdown files Ship's Records'
    own listing passes over (S1 register RA3-1: never promoted) are named, because the snapshot is where they survive.
    """
    from datetime import UTC, datetime

    from probos.identity import generate_ship_did
    from probos.knowledge.archive_ledger import SnapshotRecord
    from probos.knowledge.records_snapshot import prepare_snapshot

    root = data_dir / _SNAPSHOT_SOURCE
    started = _generation_started(data_dir)
    if started is None:  # read a moment ago as the timeline; another process removed it since
        raise RuntimeError("AD-1341 S6: ontology/instance_id disappeared during the reset")
    listed = await _records_listing(config, root)
    ship_did = generate_ship_did(timeline_id)
    prepared = prepare_snapshot(
        root, _snapshots_dir(config), timeline_id=timeline_id, ship_did=ship_did, started=started,
        ended=datetime.now(UTC),
    )
    if prepared is None:
        return "Ship's Records snapshot: Ship's Records hold no file to keep."
    result = prepared.result
    ledger = _configured_ledger(config)
    try:
        await ledger.initialize()
        snapshot_id = await ledger.record_snapshot(SnapshotRecord(
            timeline_id=timeline_id, ship_did=ship_did, generation_started=result.generation_started,
            generation_ended=result.generation_ended, relative_path=result.relative_path, sha256=result.sha256,
            file_count=result.file_count, total_bytes=result.total_bytes,
        ))
        prepared.publish()  # AD-1341 S6: recorded first, then put in place
    except BaseException:
        prepared.discard()
        raise
    finally:
        await ledger.close()
    note = (
        f"Ship's Records snapshot {snapshot_id}: {result.file_count} file(s), {result.total_bytes} bytes, kept as "
        f"{result.relative_path} beside the Ship's Archive."
    )
    unlisted = [path for path in result.paths if path.endswith(".md") and path not in listed]
    if unlisted:  # S1 register RA3-1: these were never promoted; the snapshot is where they survive
        shown = ", ".join(unlisted[:10]) + (f" and {len(unlisted) - 10} more" if len(unlisted) > 10 else "")
        note += f"\n  {len(unlisted)} Markdown file(s) Ship's Records cannot list, never promoted, are kept in it: {shown}"
    return note


def _show_snapshot_plan(config: SystemConfig, data_dir: Path, console: Console) -> None:
    """AD-1341 S6: the dry run's view of the snapshot a ``--full`` reset would keep. Reads names and sizes only."""
    from rich.markup import escape

    from probos.knowledge.records_snapshot import SnapshotRefused

    try:
        plan = _snapshot_plan(data_dir)
    except (SnapshotRefused, OSError) as exc:  # the reset itself would refuse; the dry run says so
        console.print(f"  [yellow]⚠ The Ship's Records snapshot would refuse this reset: {escape(str(exc))}[/yellow]")
        return
    if not plan.files:
        console.print("  Ship's Records snapshot: Ship's Records hold no file to keep.")
        return
    console.print(
        f"  Ship's Records snapshot: {len(plan.files)} file(s), {plan.total_bytes} bytes, would be kept in "
        f"{escape(str(_snapshots_dir(config)))} (.git/ and procedures/ left out)."
    )


def _show_promotion_plan(
    config: SystemConfig, data_dir: Path, skip_reason: str | None, console: Console, *, tier: int = 2,
) -> int:
    """``--dry-run`` at tier 2 or above: what the reset would promote. Reads Ship's Records; opens no archive.

    0 when the plan was shown (a reset that would refuse says so); 1 when Ship's Records could not be read.
    """
    from rich.markup import escape

    from probos.knowledge.archive_promotion import plan_promotion

    if not config.archive.enabled:
        console.print("\n  [dim]The Ship's Archive is disabled (archive.enabled): nothing would be promoted.[/dim]")
        return 0
    if skip_reason is not None:
        console.print(f"\n  Ship's Archive promotion would be skipped, recording: {escape(skip_reason.strip())}")
        if tier >= 3:  # AD-1341 S6
            console.print("  The Ship's Records snapshot would be skipped with it.")
        return 0
    try:
        timeline_id = _read_instance_id(data_dir)
        plan = asyncio.run(
            plan_promotion(_reset_records_store(config, data_dir), timeline_id=timeline_id or _UNATTRIBUTED_TIMELINE)
        )
        nature = asyncio.run(_nature_record(data_dir, timeline_id))  # AD-1341 S6: the description the reset would archive
    except Exception as exc:  # the dry run reports it; nothing is touched either way
        console.print(
            f"[red]✗[/red] The promotion plan could not be read: {escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return 1
    console.print(f"\n  Ship's Archive plan for timeline {escape(timeline_id or _UNATTRIBUTED_TIMELINE)}:")
    console.print(f"    {len(plan.records)} to promote, {len(plan.withheld)} withheld")
    for record in plan.records:
        console.print(f"    + {escape(record.source_ref)}")
    for path in plan.withheld:
        console.print(f"    - withheld: {escape(path)}")
    if nature is not None:  # AD-1341 S6: the Captain reads what a later crew would
        console.print(f"    + {escape(nature.source_ref)} (the nature description):")
        for line in nature.content.splitlines():
            console.print(f"      {escape(line)}")
    if plan.records:  # AD-1341 S3: the Captain reviews, and may veto, before the reset promotes
        console.print(
            "  [dim]probos archive pending shows what each would do now; "
            "probos archive veto SOURCE_REF --reason TEXT keeps one out of the Ship's Archive.[/dim]"
        )
    if plan.records and not timeline_id:
        console.print("  [yellow]⚠ No instance id: this reset would refuse without --skip-promotion REASON.[/yellow]")
    if tier >= 3:  # AD-1341 S6 A4: only a dry run whose preflight refuses nothing reaches this plan
        _show_snapshot_plan(config, data_dir, console)  # AD-1341 S6: what a --full reset would keep
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    """Handle ``probos archive erase ENTRY_ID --reason TEXT`` (AD-1341 S1): the Captain's erasure.

    The row is deleted and its bytes overwritten (``secure_delete``). A marker keeps the entry's id, timeline,
    source kind and ref, the reason and the time, never its title or content, and keeps that source from being
    promoted again. 0 erased or declined; 1 no such entry, or the erasure failed; 2 the archive disabled, or a
    bad id or reason. Plain ``print``: the entry's title and the reason are shown as text, never as markup.
    """
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    command = getattr(args, "archive_cmd", None)
    if command == "pending":  # AD-1341 S3: the Captain's review before canon
        return _cmd_archive_pending(args)
    if command == "veto":  # AD-1341 S3: the Captain's veto
        return _cmd_archive_veto(args)
    if command == "snapshots":  # AD-1341 S6: the Ship's Records snapshots --full resets kept
        return _cmd_archive_snapshots(args)
    if command == "erase-snapshot":  # AD-1341 S6: the Captain's erasure of one
        return _cmd_archive_erase_snapshot(args)
    if command != "erase":
        print(
            "usage: probos archive erase ENTRY_ID --reason TEXT | pending | veto SOURCE_REF --reason TEXT "
            "[--yes] [--config PATH] [--data-dir DIR]"
        )
        return 2
    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): there is nothing to erase.")
        return 2
    entry_id, reason = args.entry_id, args.reason
    if entry_id <= 0:
        print("An archive entry id is a positive integer.")
        return 2
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        print(f"--reason needs 1 to {ARCHIVE_REASON_MAX_CHARS} characters. Do not restate the entry's content.")
        return 2
    try:
        return asyncio.run(_erase_archive_entry(config, entry_id, reason, bool(getattr(args, "yes", False))))
    except Exception as exc:  # one transaction, so nothing is half-erased; the Captain sees why
        print(f"The erasure failed: {type(exc).__name__}: {exc}")
        return 1


async def _erase_archive_entry(config: SystemConfig, entry_id: int, reason: str, confirmed: bool) -> int:
    """Show the entry, ask unless ``--yes``, then erase it. The archive is closed on every exit."""
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        entry = await archive.entry_by_id(entry_id)
        if entry is None:
            print(f"No Ship's Archive entry has id {entry_id}.")
            return 1
        print(f"Ship's Archive entry {entry.id}: {entry.title}")
        print(f"  source: {entry.source_kind or '(no provenance: an AD-524 entry)'} {entry.source_ref}")
        print(f"  timeline: {entry.timeline_id}")
        if not confirmed and input("  Erase it? [y/N]: ").strip().lower() != "y":
            print("Aborted. Nothing was erased.")
            return 0
        if not await archive.erase_entry(entry_id, reason):
            print(f"No Ship's Archive entry has id {entry_id}.")
            return 1
    finally:
        await archive.close()
    print(
        f"Erased Ship's Archive entry {entry_id}. A marker records the erasure: if its source is still in Ship's "
        "Records, it will not be promoted again."
    )
    return 0


def _cmd_archive_pending(args: argparse.Namespace) -> int:
    """``probos archive pending`` (AD-1341 S3): the Captain's review of what the next promotion would archive.

    Every Ship's Records document that meets its source's criterion, with what promoting it now would do: archive it
    (new, or a revision of the entries named), nothing (already archived), or never (vetoed or erased by the
    Captain); then what is withheld (C1). It reads Ship's Records and the Ship's Archive and records nothing; opening
    the archive brings its schema up to date, as ``erase`` does. 0 shown; 1 a read failed; 2 the archive disabled.
    Plain ``print``: a path is shown as text, never as markup.
    """
    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:  # AD-1341 S3: a disabled archive is never opened, so pending creates no file
        print("The Ship's Archive is disabled (archive.enabled): nothing is promoted, so there is nothing to review.")
        return 2
    data_dir = Path(getattr(args, "data_dir", None) or _default_data_dir())
    timeline_id = _read_instance_id(data_dir) or _UNATTRIBUTED_TIMELINE
    try:
        review = asyncio.run(_review_pending_promotion(config, data_dir, timeline_id))
        nature = asyncio.run(_pending_nature(config, data_dir))  # AD-1341 S6: this generation's nature description
    except Exception as exc:  # nothing is recorded either way; the Captain sees why
        print(f"The review could not be read: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"Ship's Archive review for timeline {timeline_id}: {len(review.sources)} eligible, "
        f"{len(review.withheld)} withheld"
    )
    for pending in review.sources:
        print(f"  {_pending_label(pending.state)}: {pending.record.source_ref}")
    if nature is not None:  # AD-1341 S6: the next reset would archive it too; probos archive veto keeps it out
        print(f"  {_pending_label(nature.state)}: {nature.record.source_ref} (the nature description):")
        print(f"    {nature.record.title}")
        for line in nature.record.content.splitlines():  # AD-1341 S6 A2 (B-F1): the Captain reads the text itself
            print(f"    {line}")
    for path in review.withheld:
        print(f"  - withheld: {path}")
    if review.sources or nature is not None:
        print(
            "Veto a source: probos archive veto SOURCE_REF --reason TEXT. "
            "Erase an archived entry: probos archive erase ENTRY_ID --reason TEXT."
        )
    return 0


async def _review_pending_promotion(config: SystemConfig, data_dir: Path, timeline_id: str) -> PromotionReview:
    """The review over this vessel's Ship's Records and the configured archive; the archive is closed on every exit."""
    from probos.knowledge.archive_promotion import review_promotion

    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        return await review_promotion(_reset_records_store(config, data_dir), archive, timeline_id=timeline_id)
    finally:
        await archive.close()


def _pending_label(state: SourceState) -> str:
    """What promoting a source now would do, as ``probos archive pending`` shows it (AD-1341 S3)."""
    from probos.knowledge.archive_store import PromotionOutcome

    entries = ", ".join(str(entry_id) for entry_id in state.entry_ids)
    if state.outcome is PromotionOutcome.ERASED:
        return "x erased by the Captain"
    if state.outcome is PromotionOutcome.VETOED:
        return "x vetoed by the Captain"
    if state.outcome is PromotionOutcome.PRESENT:
        return f"= already archived (entry {entries})"
    return f"+ would be promoted (a revision of entry {entries})" if entries else "+ would be promoted"


def _cmd_archive_veto(args: argparse.Namespace) -> int:
    """``probos archive veto SOURCE_REF --reason TEXT`` (AD-1341 S3): the Captain vetoes a source before it is archived.

    The source must be one the next promotion would archive (``probos archive pending`` lists them). The veto keeps the
    source's kind and path, the reason, the timeline and the time, never its title or content, and no later promotion
    archives that source, with any content. A source already archived is refused: erase its entry instead. 0 vetoed,
    already vetoed, already erased, or declined; 1 not a pending source, already archived, or the veto failed; 2 the
    archive disabled, or a blank source or a bad reason. Plain ``print``.
    """
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): nothing is promoted, so there is nothing to veto.")
        return 2
    source_ref, reason = args.source_ref.strip(), args.reason
    if not source_ref:
        print("A source is its Ship's Records path, as probos archive pending lists it.")
        return 2
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        print(f"--reason needs 1 to {ARCHIVE_REASON_MAX_CHARS} characters. Do not restate the source's content.")
        return 2
    data_dir = Path(getattr(args, "data_dir", None) or _default_data_dir())
    try:
        return asyncio.run(_veto_pending_source(config, data_dir, source_ref, reason, bool(getattr(args, "yes", False))))
    except Exception as exc:  # one statement, so nothing is half-recorded; the Captain sees why
        print(f"The veto failed: {type(exc).__name__}: {exc}")
        return 1


async def _veto_pending_source(
    config: SystemConfig, data_dir: Path, source_ref: str, reason: str, confirmed: bool,
) -> int:
    """Find the pending source, show it, ask unless ``--yes``, then record the veto. The archive is closed on every exit."""
    from probos.knowledge.archive_promotion import NATURE_DESCRIPTION_PREFIX, plan_promotion
    from probos.knowledge.archive_store import SourceKind, VetoOutcome

    timeline_id = _read_instance_id(data_dir)
    plan = await plan_promotion(
        _reset_records_store(config, data_dir), timeline_id=timeline_id or _UNATTRIBUTED_TIMELINE,
    )
    record = next((item for item in plan.records if item.source_ref == source_ref), None)
    if record is None and source_ref.startswith(NATURE_DESCRIPTION_PREFIX):  # AD-1341 S6: this generation's description
        nature = await _nature_record(data_dir, timeline_id)
        record = nature if nature is not None and nature.source_ref == source_ref else None
    if record is None:
        print(
            f"{source_ref} is not a source the next promotion would archive (not in Ship's Records, not eligible, "
            "or withheld). probos archive pending lists the sources."
        )
        return 1
    print(f"Ship's Records source {record.source_ref}: {record.title}")
    print(f"  kind: {record.source_kind.value}")
    if record.source_kind is SourceKind.NATURE_DESCRIPTION:  # AD-1341 S6 A2 (B-F1): the text it keeps out
        for line in record.content.splitlines():
            print(f"    {line}")
    if not confirmed and input("  Veto its promotion into the Ship's Archive? [y/N]: ").strip().lower() != "y":
        print("Aborted. Nothing was vetoed.")
        return 0
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        outcome = await archive.veto_source(record.source_kind, record.source_ref, reason, timeline_id=timeline_id)
    finally:
        await archive.close()
    if outcome is VetoOutcome.ARCHIVED:
        print(
            "An entry from this source is already in the Ship's Archive, and a veto does not remove it. "
            "probos archive pending shows its id; erase it with probos archive erase ENTRY_ID --reason TEXT."
        )
        return 1
    if outcome is VetoOutcome.ERASED:
        print("The Captain already erased this source's entry, so it is never promoted again. Nothing changed.")
        return 0
    if outcome is VetoOutcome.ALREADY_VETOED:
        print("This source is already vetoed. Nothing changed.")
        return 0
    print("Vetoed: this source is never promoted into the Ship's Archive. The veto and its reason are recorded.")
    return 0


def _cmd_archive_snapshots(args: argparse.Namespace) -> int:
    """``probos archive snapshots`` (AD-1341 S6): the Ship's Records snapshots ``--full`` resets kept.

    Each with its id, name, whether its file is there (``present``, ``missing``) or the Captain erased it, what it
    holds and the generation's dates. Reads the archive; records nothing. 0 shown; 1 the archive could not be read;
    2 the archive disabled. Plain ``print``: a name is shown as text, never as markup.
    """
    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): no snapshot is kept.")
        return 2
    try:
        entries = asyncio.run(_read_snapshot_entries(config))
    except Exception as exc:  # nothing is recorded either way; the Captain sees why
        print(f"The snapshots could not be read: {type(exc).__name__}: {exc}")
        return 1
    directory = _snapshots_dir(config)
    print(f"Ship's Records snapshots: {len(entries)}, in {directory}")
    for entry in entries:
        print(
            f"  {entry.id}: {entry.relative_path} {_snapshot_state(entry, directory)}; {entry.file_count} file(s), "
            f"{entry.total_bytes} bytes; generation {entry.generation_started} to {entry.generation_ended}"
        )
    if entries:
        print("Erase one: probos archive erase-snapshot SNAPSHOT_ID --reason TEXT.")
    return 0


def _snapshot_state(entry: SnapshotEntry, directory: Path) -> str:
    """What ``probos archive snapshots`` shows of one snapshot's file (AD-1341 S6)."""
    from probos.knowledge.records_snapshot import is_snapshot_relative_path

    if entry.erased_at is not None:  # AD-1341 S6 A4: an erasure that did not finish says so until it does
        if is_snapshot_relative_path(entry.relative_path) and os.path.lexists(directory / entry.relative_path):
            return "(erased by the Captain; its file remains: run probos archive erase-snapshot again)"
        return "(erased by the Captain)"
    if not is_snapshot_relative_path(entry.relative_path):
        return "(not a snapshot's name: never opened)"
    return "(present)" if (directory / entry.relative_path).is_file() else "(missing)"


async def _read_snapshot_entries(config: SystemConfig) -> tuple[SnapshotEntry, ...]:
    """Every recorded snapshot; the ledger is closed on every exit (AD-1341 S6)."""
    ledger = await _open_ledger(config)
    try:
        return await ledger.snapshot_entries()
    finally:
        await ledger.close()


def _cmd_archive_erase_snapshot(args: argparse.Namespace) -> int:
    """``probos archive erase-snapshot SNAPSHOT_ID --reason TEXT`` (AD-1341 S6): the Captain erases one snapshot.

    The ledger's row is marked erased first (the reason and the time; no content), then the file is deleted, so no
    snapshot is removed unrecorded. A deletion that fails is reported, and the same command finishes it. 0 erased,
    already erased or declined; 1 no such snapshot, a row that names no snapshot, or a failure; 2 the archive
    disabled, or a bad id or reason. Plain ``print``.
    """
    from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS

    config, _ = _load_config_with_fallback(getattr(args, "config", None))
    if not config.archive.enabled:
        print("The Ship's Archive is disabled (archive.enabled): there is no snapshot to erase.")
        return 2
    snapshot_id, reason = args.snapshot_id, args.reason
    if snapshot_id <= 0:
        print("A snapshot id is a positive integer, as probos archive snapshots lists it.")
        return 2
    if not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        print(f"--reason needs 1 to {ARCHIVE_REASON_MAX_CHARS} characters.")
        return 2
    try:
        return asyncio.run(_erase_snapshot(config, snapshot_id, reason, bool(getattr(args, "yes", False))))
    except Exception as exc:  # the marker is one statement; the Captain sees why
        print(f"The erasure failed: {type(exc).__name__}: {exc}")
        return 1


async def _erase_snapshot(config: SystemConfig, snapshot_id: int, reason: str, confirmed: bool) -> int:
    """Show the snapshot, ask unless ``--yes``, mark it erased, then delete its file. The ledger is closed on every exit."""
    from probos.knowledge.records_snapshot import SnapshotRefused, is_snapshot_relative_path, retained_alias

    ledger = await _open_ledger(config)
    try:
        entry = await ledger.snapshot_by_id(snapshot_id)
        if entry is None:
            print(f"No Ship's Records snapshot has id {snapshot_id}.")
            return 1
        if not is_snapshot_relative_path(entry.relative_path):  # AD-1341 S6: a row never names a file outside the snapshots
            print(f"Snapshot {snapshot_id} names {entry.relative_path!r}, which is not a snapshot's name. Nothing was erased.")
            return 1
        problem = _snapshot_file_problem(_snapshots_dir(config), entry.relative_path)  # A2: before the marker
        if problem:
            print(f"Snapshot {snapshot_id}: {problem}. Nothing was erased.")
            return 1
        print(f"Ship's Records snapshot {entry.id}: {entry.relative_path} ({entry.file_count} file(s), timeline {entry.timeline_id})")
        if entry.erased_at is None:
            if not confirmed and input("  Erase it? Its file is deleted. [y/N]: ").strip().lower() != "y":
                print("Aborted. Nothing was erased.")
                return 0
            await ledger.mark_snapshot_erased(snapshot_id, reason)  # the marker first
    finally:
        await ledger.close()
    path = _snapshots_dir(config) / entry.relative_path
    try:
        alias = retained_alias(path)  # AD-1341 S6 A4 (A-R2-F2): the temporary name publish could not remove
        for name in (*([alias] if alias is not None else []), path):  # A4: the alias first, so a rerun still finds it
            name.unlink(missing_ok=True)
    except (OSError, SnapshotRefused) as exc:  # A5: a refusal here means the name changed after the check (R28)
        print(f"The erasure is recorded, but the file remains at {path}: {type(exc).__name__}: {exc}. Run the same command again.")
        return 1
    print(f"Erased Ship's Records snapshot {snapshot_id}: a marker keeps its name and the reason; its file is deleted.")
    return 0


def _snapshot_file_problem(directory: Path, relative_path: str) -> str:
    """AD-1341 S6 A2 (A-F3): why a recorded snapshot's path must not be erased, or ``""`` when it may. ``lstat`` only.

    Neither the snapshots directory nor the timeline's directory may be a link or junction, and what stands at the
    snapshot's own name, when anything does, must be a regular file: an erasure deletes only a snapshot inside the
    snapshots directory. Nothing there is fine (a ``missing`` row may still be marked). Any other ``OSError``
    propagates, and the erasure fails before its marker. A5 (A-R3-F1): a temporary name beside the snapshot whose
    identity cannot be shown (``retained_alias`` refuses: a file index of 0) is refused here too, before the marker.
    """
    import stat

    from probos.knowledge.records_snapshot import SnapshotRefused, is_link_or_junction, lstat_or_none, retained_alias

    path = directory / relative_path
    for component in (directory, path.parent):
        if is_link_or_junction(component):  # AD-1341 S6 A2: an erasure never follows one
            return f"{component} is a link or junction; an erasure deletes only inside the snapshots directory"
    status = lstat_or_none(path)
    if status is not None and not stat.S_ISREG(status.st_mode):  # a directory, a link or a special file there
        return f"{path} is not a snapshot's file"
    try:
        retained_alias(path)  # AD-1341 S6 A5 (A-R3-F1): a temporary name of unknown identity refuses before the marker
    except SnapshotRefused as exc:
        return str(exc)
    return ""


def _clear_nature(config: SystemConfig, tier: int, data_dir: Path, console: Console) -> bool:
    """AD-1341 S6: ``--clean-slate``. Record the clearance in the Ship's Archive, then delete nature; True when done.

    Nature here is the procedure store's directory (``procedures/``: ``procedures.db``, the AD-1326 challenger ledger
    and the procedures' semantic index). The marker is written first, so nature is never deleted unrecorded. A link,
    a junction or a file at that name is refused, never followed. A deletion that fails part-way is reported; the
    reset refuses before its tier loop, and the same command finishes it. The skill catalog (``config/skills``), the
    Captain's grants, the Ship's Archive and its snapshots are never touched.
    """
    from rich.markup import escape

    procedures = data_dir / _NATURE_DIR
    problem = _nature_dir_problem(data_dir)  # AD-1341 S6 A2: asked again where it deletes
    if problem:
        console.print(f"[red]✗[/red] {escape(problem)}")
        return False
    try:
        count = asyncio.run(_record_nature_clearance(config, data_dir, tier))  # AD-1341 S6: the marker first
    except Exception as exc:  # the marker failed, so nothing is deleted; the Captain sees why
        console.print(
            f"[red]✗[/red] The clean slate could not be recorded, so nothing was cleared: "
            f"{escape(type(exc).__name__)}: {escape(str(exc))}"
        )
        return False
    try:
        if procedures.exists():
            shutil.rmtree(procedures, onerror=_force_remove_readonly)
    except OSError as exc:
        console.print(
            f"[red]✗[/red] The clean slate is recorded but did not finish: {escape(type(exc).__name__)}: "
            f"{escape(str(exc))}. Run the same command again."
        )
        return False  # AD-1341 S6: the deletion is recorded and unfinished; the reset refuses before its tier loop
    console.print(f"  Nature cleared (--clean-slate): {_NATURE_DIR}/ held {count} procedure(s); recorded in the Ship's Archive.")
    return True


async def _record_nature_clearance(config: SystemConfig, data_dir: Path, tier: int) -> int:
    """AD-1341 S6: the clean slate's marker: the timeline, the tier, what is cleared and the procedures it held."""
    from probos.knowledge.archive_ledger import NatureClearanceRecord
    from probos.knowledge.nature_description import PROCEDURES_DB, count_procedures

    try:
        count = await count_procedures(data_dir / PROCEDURES_DB, _open_read_only)
    except Exception:  # log-and-degrade: an unreadable store is still the Captain's to clear; the marker says -1
        logging.getLogger(__name__).warning(
            "AD-1341 S6: the procedure store could not be counted before the clean slate", exc_info=True,
        )
        count = -1
    cleared = (f"{_NATURE_DIR}/",) if (data_dir / _NATURE_DIR).exists() else ()
    ledger = await _open_ledger(config)
    try:
        await ledger.record_nature_clearance(NatureClearanceRecord(
            timeline_id=_read_instance_id(data_dir), reset_tier=tier, cleared=cleared, procedure_count=count,
        ))
    finally:
        await ledger.close()
    return count


def _nature_dir_problem(data_dir: Path) -> str:
    """AD-1341 S6 A2: why ``--clean-slate`` must not clear ``{data_dir}/procedures``, or ``""`` when it may.

    One ``lstat``, never followed: a link or junction there (it may lead out of the data directory), anything but a
    directory, or a name that cannot be inspected refuses. Nothing there is fine: nothing to clear. The preflight asks
    before the promotion reads the store through it (B-F3, C-F2); ``_clear_nature`` asks again where it deletes.
    """
    import stat

    from probos.knowledge.records_snapshot import is_link_status, lstat_or_none

    procedures = data_dir / _NATURE_DIR
    try:
        status = lstat_or_none(procedures)
    except OSError as exc:
        return f"{procedures} cannot be inspected ({exc}); --clean-slate clears nothing it cannot see."
    if status is None:
        return ""
    if is_link_status(status):  # AD-1341 S6: never followed out of the data directory
        return f"{procedures} is a link; --clean-slate clears only the data directory's own."
    if not stat.S_ISDIR(status.st_mode):  # AD-1341 S6 A2: a file at that name is refused too
        return f"{procedures} is not the procedure store's directory; nothing was cleared."
    return ""


def _close_generation(config: SystemConfig, closing: GenerationRecord, console: Console) -> bool:
    """AD-1341 S6 A2 (C-F3): record the generation's close, last before the tier loop; True when recorded.

    After the promotion, the snapshot and any clean slate have succeeded, so the Ship's Archive never shows a
    generation closed while its crew's files remain. A failure refuses the reset before its tier loop; the same
    command finishes it (the promotion is idempotent, the description is kept once per generation).
    """
    from rich.markup import escape

    try:
        asyncio.run(_record_generation(config, closing))
    except Exception as exc:  # the close failed; the reset refuses and the Captain sees why
        console.print(
            f"[red]✗[/red] The generation's close could not be recorded: {escape(type(exc).__name__)}: "
            f"{escape(str(exc))}"
        )
        return False  # AD-1341 S6 A2: not closed; the reset refuses before its tier loop
    return True


async def _record_generation(config: SystemConfig, closing: GenerationRecord) -> None:
    """AD-1341 S6 A2: S1's ``record_generation``, on its own archive connection; the archive is closed on every exit."""
    archive = _configured_archive_store(config)
    await archive.initialize()
    try:
        await archive.record_generation(closing)
    finally:
        await archive.close()


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
    init_parser.add_argument(
        "--security-profile",
        choices=("strict", "relaxed"),
        default="strict",
        help="Security defaults to bake into the generated config (default: strict)",
    )

    # --- probos setup / probos model (AD-1135) ---
    _add_setup_parser(subparsers)

    # --- probos doctor (AD-484) ---
    doctor_parser = subparsers.add_parser("doctor", help="Run a diagnostic check on the ProbOS environment")
    # AD-1137, SUPPRESS as for setup: a --config or --data-dir given before `doctor` (the root parser's) is kept.
    doctor_parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS,
        help="Check this config file (default: the one probos loads)",
    )
    doctor_parser.add_argument(
        "--data-dir", type=Path, metavar="DIR", default=argparse.SUPPRESS,
        help="Check this data directory (default: platform-specific)",
    )

    # --- probos pairing (AD-802) ---
    pairing_parser = subparsers.add_parser(
        "pairing",
        help="Manage DM pairings for inbound channel adapters (AD-802)",
    )
    pairing_sub = pairing_parser.add_subparsers(dest="pairing_cmd", required=True)
    pairing_pending = pairing_sub.add_parser("pending", help="List pending pairings awaiting approval")
    pairing_pending.add_argument("--channel", type=str, default=None)
    pairing_list = pairing_sub.add_parser("list", help="List active paired users")
    pairing_list.add_argument("--channel", type=str, default=None)
    pairing_approve = pairing_sub.add_parser("approve", help="Approve a pending pairing by code")
    pairing_approve.add_argument("channel", type=str, help="Channel identifier (e.g. telegram, slack)")
    pairing_approve.add_argument("code", type=str, help="Pairing code")
    pairing_approve.add_argument(
        "--cap",
        type=str,
        default=None,
        help="Comma-separated capability override (e.g. 'dm.send,ward_room.post')",
    )
    pairing_approve.add_argument(
        "--ttl-days",
        type=float,
        default=None,
        help="Session TTL in days (default: 7)",
    )
    pairing_revoke = pairing_sub.add_parser("revoke", help="Revoke an active pairing by DID")
    pairing_revoke.add_argument("did", type=str, help="DID of the paired user")

    # --- probos channel (AD-803a Telegram setup; AD-804..807 future) ---
    channel_parser = subparsers.add_parser(
        "channel",
        help="Configure channel adapters (Telegram, Slack, …) — AD-803a+",
    )
    channel_sub = channel_parser.add_subparsers(dest="channel_cmd", required=True)
    channel_tg = channel_sub.add_parser(
        "telegram",
        help="Manage the Telegram channel adapter",
    )
    channel_tg_sub = channel_tg.add_subparsers(dest="channel_tg_cmd", required=True)
    channel_tg_setup = channel_tg_sub.add_parser("setup", help="Interactive token entry + validation")
    channel_tg_setup.add_argument(
        "--token",
        type=str,
        default=None,
        help="Bot Father token (skips the interactive prompt)",
    )
    channel_sl = channel_sub.add_parser(
        "slack",
        help="Manage the Slack channel adapter",
    )
    channel_sl_sub = channel_sl.add_subparsers(dest="channel_sl_cmd", required=True)
    channel_sl_setup = channel_sl_sub.add_parser("setup", help="Interactive token entry + validation")
    channel_sl_setup.add_argument(
        "--token",
        type=str,
        default=None,
        help="xoxb-… bot user OAuth token (skips the interactive prompt)",
    )
    channel_mx = channel_sub.add_parser(
        "matrix",
        help="Manage the Matrix channel adapter",
    )
    channel_mx_sub = channel_mx.add_subparsers(dest="channel_mx_cmd", required=True)
    channel_mx_setup = channel_mx_sub.add_parser("setup", help="Login + persist access token")
    channel_mx_setup.add_argument(
        "--homeserver",
        type=str,
        default=None,
        help="Homeserver URL (e.g. https://matrix.org)",
    )
    channel_mx_setup.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="Full Matrix ID (e.g. @yeo:matrix.org)",
    )
    channel_mx_setup.add_argument(
        "--password",
        type=str,
        default=None,
        help="Password (skips interactive prompt; prefer the prompt to avoid shell history)",
    )

    # --- probos crew-token (BF-908) ---
    crew_token_parser = subparsers.add_parser(
        "crew-token",
        help="Set, rotate, clear or show the crew-scope token in the OS keyring (BF-908; the Captain's action)",
    )
    # SUPPRESS as for doctor: a --config given before `crew-token` (the root parser's) is kept.
    crew_token_parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS,
        help="The config file the vessel loads (default: the one probos loads)",
    )
    crew_token_sub = crew_token_parser.add_subparsers(dest="crew_token_cmd", required=True)
    for _verb, _verb_help in (
        ("set", "Store a token in the OS keyring (prompted twice, never shown)"),
        ("rotate", "Replace the token the OS keyring holds"),
    ):
        _verb_parser = crew_token_sub.add_parser(_verb, help=_verb_help)
        _verb_parser.add_argument(
            "--stdin", action="store_true",
            help="Read the token from one line of standard input; it is never taken from the command line",
        )
    crew_token_sub.add_parser("clear", help="Delete the token from the OS keyring (never refused)")
    crew_token_sub.add_parser("status", help="Say where the token comes from, never its value")

    # --- probos migrate (AD-808) ---
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Import operator state from OpenClaw / Hermes Agent (AD-808)",
    )
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_source", required=True)
    for _src in ("openclaw", "hermes"):
        _p = migrate_sub.add_parser(
            _src, help=f"Migrate from {_src} (~/.{_src}/)",
        )
        _p.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported, do nothing",
        )
        _p.add_argument(
            "--preset",
            choices=("user-data", "full"),
            default="user-data",
            help="user-data skips API keys / secrets (default); full includes them",
        )
        _p.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace existing files at the target paths",
        )
        _p.add_argument(
            "--source-dir",
            type=Path,
            default=None,
            help=f"Override source directory (default: ~/.{_src})",
        )

    # --- probos verify-snapshot (AD-1265) ---
    verify_snapshot_parser = subparsers.add_parser(
        "verify-snapshot",
        help=(
            "Check a promoted backup snapshot against its manifest "
            "(read-only, safe on a live vessel) (AD-1265)"
        ),
    )
    verify_snapshot_parser.add_argument(
        "--snapshot", type=Path, required=True,
        help="Path to a promoted snapshot directory (data/backups/<timestamp>)",
    )
    # Deliberately no --data-dir / --config: the check reads the snapshot
    # named on the command line and nothing else, so accepting them would
    # promise a scoping the handler does not perform.

    # --- probos backup-reclaim (AD-1296) ---
    backup_reclaim_parser = subparsers.add_parser(
        "backup-reclaim",
        help=(
            "List (and optionally delete) backup working directories the "
            "automatic sweep cannot prove are finished (AD-1296)"
        ),
    )
    backup_reclaim_parser.add_argument(
        "--backup-root", type=Path, required=True,
        help="Backup root to inspect (data/backups)",
    )
    backup_reclaim_parser.add_argument(
        "--force", action="store_true",
        help="Delete the listed directories (refuses while a vessel owns the data dir)",
    )
    backup_reclaim_parser.add_argument(
        "--data-dir", type=Path, default=argparse.SUPPRESS,  # BF-916: a --data-dir before the command is kept
        help="Data directory checked for a running vessel; only used with --force",
    )

    # --- probos rebuild-episodic (AD-819) ---
    rebuild_parser = subparsers.add_parser(
        "rebuild-episodic",
        help="Reconstruct ChromaDB episodic memory from surviving ward room (AD-819)",
    )
    # BF-916, SUPPRESS as for doctor: a --data-dir or --config before `rebuild-episodic` (the root parser's) is kept.
    rebuild_parser.add_argument(
        "--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory (default: platform path)"
    )
    rebuild_parser.add_argument(
        "--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",
    )
    rebuild_parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and synthesize episodes but don't write to ChromaDB",
    )
    rebuild_parser.add_argument(
        "--source", choices=("wardroom",), default="wardroom",
        help="Which source store to replay (default: wardroom)",
    )
    rebuild_parser.add_argument(
        "--since", type=str, default=None,
        help="Only replay rows created at or after this ISO date (e.g. 2026-05-01)",
    )

    # --- probos qa run-contracts (AD-713 / better-agents) ---
    qa_parser = subparsers.add_parser("qa", help="Quality / behavior contract commands")
    qa_sub = qa_parser.add_subparsers(dest="qa_cmd", required=True)
    qa_run = qa_sub.add_parser(
        "run-contracts", help="Evaluate behavior contracts in a file or directory"
    )
    qa_run.add_argument(
        "path",
        type=str,
        help="Path to a contract file or directory of contracts",
    )

    # --- probos serve ---
    serve_parser = subparsers.add_parser("serve", help="Start HTTP + WebSocket API server")
    # BF-916, SUPPRESS as for doctor: a --config, --fresh or --data-dir before `serve` (the root parser's) is kept.
    serve_parser.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    serve_parser.add_argument("--fresh", action="store_true", default=argparse.SUPPRESS, help="Cold start")
    serve_parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address")
    serve_parser.add_argument("--port", type=int, default=18900, help="Bind port")
    serve_parser.add_argument("--interactive", action="store_true", help="Also run interactive shell")
    serve_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Detailed boot log (INFO+ on console, per-pool detail)",
    )
    serve_parser.add_argument("--discord", action="store_true", help="Also start Discord bot adapter")
    serve_parser.add_argument(
        "--force-unclean", action="store_true",
        help="AD-820: bypass the previous-shutdown integrity check (use only "
             "for recovery after a known-unclean shutdown; risks segfault if "
             "ChromaDB's HNSW index is torn).",
    )

    # --- probos reset ---
    reset_parser = subparsers.add_parser("reset", help="Clear learned state (tiered: --soft, default, --full)")
    reset_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    reset_parser.add_argument("--soft", action="store_true", help="Tier 1: Reboot — runtime transients only")
    reset_parser.add_argument("--full", action="store_true", help="Tier 3: Maiden Voyage — everything including records")
    reset_parser.add_argument("--dry-run", action="store_true", help="Show what would be cleared, do nothing")
    reset_parser.add_argument("--wipe-records", action="store_true", help="(deprecated, use --full)")
    reset_parser.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    reset_parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
    reset_parser.add_argument(
        "--skip-promotion", type=str, default=None, metavar="REASON",
        help="AD-1341: reset without promoting Ship's Records into the Ship's Archive first; "
             "the reason (1-500 characters) is recorded",
    )
    reset_parser.add_argument(
        "--clean-slate", action="store_true",
        help="AD-1341 S6: with tier 2 or 3, also clear nature (the Cognitive JIT procedure store), recorded first",
    )

    # --- probos archive (AD-1341 S1, S3): the Captain's erasure, review and veto ---
    archive_parser = subparsers.add_parser(
        "archive", help="The Ship's Archive: the Captain's review, veto and erasure (AD-1341)",
    )
    archive_sub = archive_parser.add_subparsers(dest="archive_cmd", required=True)
    archive_erase = archive_sub.add_parser(
        "erase", help="Erase one Ship's Archive entry; its source is never promoted again",
    )
    archive_erase.add_argument("entry_id", type=int, help="The entry's id")
    archive_erase.add_argument(
        "--reason", type=str, required=True,
        help="Why, in 1-500 characters; it is recorded. Do not restate the entry's content.",
    )
    archive_erase.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_erase.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    # AD-1341 S3: SUPPRESS keeps a root --config or --data-dir given before the command (S1 D19).
    archive_pending = archive_sub.add_parser(
        "pending", help="List what the next promotion would archive, and what the Captain vetoed or erased",
    )
    archive_pending.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    archive_pending.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
    archive_veto = archive_sub.add_parser(
        "veto", help="Veto one Ship's Records source: it is never promoted into the Ship's Archive",
    )
    archive_veto.add_argument("source_ref", type=str, help="The source's Ship's Records path, as pending lists it")
    archive_veto.add_argument(
        "--reason", type=str, required=True,
        help="Why, in 1-500 characters; it is recorded. Do not restate the source's content.",
    )
    archive_veto.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_veto.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    archive_veto.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
    # AD-1341 S6: the Ship's Records snapshots --full resets kept beside the archive, and the Captain's erasure of one.
    archive_snapshots = archive_sub.add_parser(
        "snapshots", help="List the Ship's Records snapshots --full resets kept beside the Ship's Archive",
    )
    archive_snapshots.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    archive_erase_snapshot = archive_sub.add_parser(
        "erase-snapshot", help="Erase one Ship's Records snapshot: a marker records it, then its file is deleted",
    )
    archive_erase_snapshot.add_argument("snapshot_id", type=int, help="The snapshot's id, as snapshots lists it")
    archive_erase_snapshot.add_argument(
        "--reason", type=str, required=True, help="Why, in 1-500 characters; it is recorded.",
    )
    archive_erase_snapshot.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    archive_erase_snapshot.add_argument(
        "--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",
    )

    args = parser.parse_args()

    if args.command in ("setup", "model"):
        # sync command; needs no event-loop policy
        import sys
        sys.exit(_cmd_setup(args))

    # Windows ProactorEventLoop doesn't support add_reader required by pyzmq.
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if args.command == "init":
        _cmd_init(args)
        return

    if args.command == "doctor":
        # AD-484: doctor returns non-zero exit code on failure
        import sys
        sys.exit(_cmd_doctor(args))

    if args.command == "crew-token":  # BF-908
        import sys
        sys.exit(_cmd_crew_token(args))

    if args.command == "pairing":
        import sys
        sys.exit(_cmd_pairing(args))

    if args.command == "channel":
        import sys
        sys.exit(_cmd_channel(args))

    if args.command == "migrate":
        import sys
        sys.exit(_cmd_migrate(args))

    if args.command == "verify-snapshot":
        import sys
        sys.exit(_cmd_verify_snapshot(args))

    if args.command == "backup-reclaim":
        import sys
        sys.exit(_cmd_backup_reclaim(args))

    if args.command == "rebuild-episodic":
        import sys
        sys.exit(_cmd_rebuild_episodic(args))

    if args.command == "qa":
        import sys
        if getattr(args, "qa_cmd", None) == "run-contracts":
            sys.exit(_cmd_qa_run_contracts(args))
        sys.exit(2)

    if args.command == "reset":
        import sys
        sys.exit(_cmd_reset(args))  # AD-1341 S1: 1 refused, 2 a bad --skip-promotion

    if args.command == "archive":  # AD-1341 S1: the Captain's erasure
        import sys
        sys.exit(_cmd_archive(args))

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
                verbose=args.verbose,
                force_unclean=getattr(args, "force_unclean", False),
            ))
        except KeyboardInterrupt:
            pass
        return

    # Default: interactive shell (backward compatible)
    try:
        asyncio.run(_boot_and_run(config_path=args.config, fresh=args.fresh, data_dir=args.data_dir, verbose=False))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
