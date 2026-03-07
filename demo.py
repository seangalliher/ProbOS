"""ProbOS demo — boot the runtime, show consensus layer catching corruption.

Uses Rich panels for display instead of raw logging.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add src to path when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import logging

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from probos.agents.corrupted import CorruptedFileReaderAgent
from probos.experience import panels
from probos.experience.renderer import ExecutionRenderer
from probos.mesh.routing import REL_AGENT, REL_INTENT
from probos.runtime import ProbOSRuntime


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def _section(console: Console, title: str) -> None:
    console.print()
    console.rule(f"[bold]{title}[/bold]")
    console.print()


async def main() -> None:
    _setup_logging()
    console = Console()

    banner = Text()
    banner.append("ProbOS Demo", style="bold blue")
    banner.append(" \u2014 Consensus, Trust & Cognitive Pipeline", style="italic")
    console.print(Panel(banner, style="blue"))

    with tempfile.TemporaryDirectory(prefix="probos_demo_") as tmp:
        runtime = ProbOSRuntime(data_dir=tmp)

        # Boot
        with console.status("[bold blue]Starting ProbOS...[/bold blue]"):
            await runtime.start()

        console.print(panels.render_status_panel(runtime.status()))

        # --------------------------------------------------------
        # Demo 1: File read with consensus — 3 agents, verified
        # --------------------------------------------------------
        _section(console, "Demo 1: Consensus File Read (Honest Agents)")

        test_file = Path(tmp) / "test_data.txt"
        test_file.write_text("Hello from ProbOS!\nLine 2\nLine 3\n")

        result = await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        consensus = result["consensus"]
        console.print(
            f"  Consensus: [bold]{consensus.outcome.value}[/bold] "
            f"(approval ratio: {consensus.approval_ratio:.3f}, "
            f"votes: {len(consensus.votes)})"
        )
        for v in consensus.votes:
            icon = "[green]\u2713[/green]" if v.approved else "[red]\u2717[/red]"
            console.print(
                f"    {icon} Agent {v.agent_id[:8]}: "
                f"confidence={v.confidence:.3f}"
            )

        console.print(f"\n  Verifications: {len(result['verifications'])}")
        for vr in result["verifications"]:
            icon = "[green]PASS[/green]" if vr.verified else "[red]FAIL[/red]"
            console.print(
                f"    [{icon}] {vr.verifier_id[:8]} -> {vr.target_agent_id[:8]}"
            )

        # --------------------------------------------------------
        # Demo 2: Inject corrupted agent
        # --------------------------------------------------------
        _section(console, "Demo 2: Inject Corrupted Agent")

        corrupted = CorruptedFileReaderAgent(pool="filesystem")
        await runtime.registry.register(corrupted)
        await corrupted.start()
        await runtime._wire_agent(corrupted)

        console.print(
            f"  Injected [red]corrupted[/red] agent: {corrupted.id[:8]}"
        )

        result = await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        consensus = result["consensus"]
        console.print(
            f"\n  Consensus: [bold]{consensus.outcome.value}[/bold] "
            f"(approval ratio: {consensus.approval_ratio:.3f})"
        )

        console.print("\n  Verifications:")
        for vr in result["verifications"]:
            icon = "[green]PASS[/green]" if vr.verified else "[red]FAIL[/red]"
            disc = f" \u2014 {vr.discrepancy}" if vr.discrepancy else ""
            console.print(
                f"    [{icon}] {vr.verifier_id[:8]} -> {vr.target_agent_id[:8]}{disc}"
            )

        failed = [v for v in result["verifications"] if not v.verified]
        console.print(
            f"\n  Red team caught [bold red]{len(failed)}[/bold red] discrepancies "
            f"out of {len(result['verifications'])} verifications"
        )

        # --------------------------------------------------------
        # Demo 3: Trust network
        # --------------------------------------------------------
        _section(console, "Demo 3: Trust Network After Corruption")

        console.print(panels.render_trust_panel(runtime.trust_network.summary()))

        corrupted_score = runtime.trust_network.get_score(corrupted.id)
        console.print(
            f"  Corrupted agent trust: [red]{corrupted_score:.4f}[/red] "
            f"(should be lower than honest agents)"
        )

        # --------------------------------------------------------
        # Demo 4: Hebbian agent-to-agent weights
        # --------------------------------------------------------
        _section(console, "Demo 4: Agent-to-Agent Hebbian Weights")

        typed_weights = runtime.hebbian_router.all_weights_typed()
        intent_weights = {k: v for k, v in typed_weights.items() if k[2] == REL_INTENT}
        agent_weights = {k: v for k, v in typed_weights.items() if k[2] == REL_AGENT}

        console.print(f"  Intent-to-agent weights: {len(intent_weights)}")
        console.print(f"  Agent-to-agent weights: {len(agent_weights)}")
        if agent_weights:
            console.print(panels.render_weight_table(
                {k: v for k, v in typed_weights.items() if k[2] == REL_AGENT}
            ))

        # --------------------------------------------------------
        # Demo 5: Write with consensus
        # --------------------------------------------------------
        _section(console, "Demo 5: Write File with Consensus")

        await runtime.create_pool("writers", "file_writer", target_size=3)

        write_path = str(Path(tmp) / "consensus_written.txt")
        write_result = await runtime.submit_write_with_consensus(
            path=write_path,
            content="This file was written with consensus approval.\n",
            timeout=5.0,
        )

        console.print(
            f"  Write consensus: [bold]{write_result['consensus'].outcome.value}[/bold] "
            f"committed={write_result['committed']}"
        )
        if write_result["committed"]:
            written_content = Path(write_path).read_text()
            console.print(f"  File content: {written_content!r}")

        # --------------------------------------------------------
        # Demo 6: NL processing with visual feedback
        # --------------------------------------------------------
        _section(console, "Demo 6: Natural Language Processing")

        renderer = ExecutionRenderer(console, runtime)
        await renderer.process_with_feedback(
            f"read the file at {test_file}"
        )

        # --------------------------------------------------------
        # Demo 7: Event log
        # --------------------------------------------------------
        _section(console, "Demo 7: Event Log")

        events = await runtime.event_log.query(category="consensus", limit=10)
        console.print(panels.render_event_log_table(events))

        total = await runtime.event_log.count()
        console.print(f"\n  Total events: {total}")

        # --------------------------------------------------------
        # Shutdown
        # --------------------------------------------------------
        _section(console, "Shutdown")

        with console.status("[bold red]Shutting down...[/bold red]"):
            await runtime.stop()
        console.print("[dim]ProbOS stopped.[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
