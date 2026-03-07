"""ProbOS demo — boot the runtime, show consensus layer catching corruption."""

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

# Add src to path when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from probos.agents.corrupted import CorruptedFileReaderAgent
from probos.runtime import ProbOSRuntime


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet down noisy loggers
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    log = logging.getLogger("demo")

    # Use a temp dir for demo data so we don't pollute the project
    with tempfile.TemporaryDirectory(prefix="probos_demo_") as tmp:
        runtime = ProbOSRuntime(data_dir=tmp)

        log.info("=" * 60)
        log.info("--- Booting ProbOS ---")
        log.info("=" * 60)
        await runtime.start()

        # Print system status
        status = runtime.status()
        log.info(
            "Status after boot:\n%s",
            json.dumps(status, indent=2, default=str),
        )

        # --------------------------------------------------------
        # Demo 1: File read with consensus — 3 agents, verified
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Demo 1: Consensus file read (honest agents) ---")
        log.info("=" * 60)

        test_file = Path(tmp) / "test_data.txt"
        test_file.write_text("Hello from ProbOS!\nLine 2\nLine 3\n")

        result = await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        consensus = result["consensus"]
        log.info(
            "Consensus: outcome=%s approval=%.3f votes=%d",
            consensus.outcome.value,
            consensus.approval_ratio,
            len(consensus.votes),
        )
        for v in consensus.votes:
            log.info(
                "  Vote: agent=%s approved=%s confidence=%.3f",
                v.agent_id[:8],
                v.approved,
                v.confidence,
            )

        log.info("Verifications: %d", len(result["verifications"]))
        for vr in result["verifications"]:
            log.info(
                "  Verify: verifier=%s target=%s verified=%s",
                vr.verifier_id[:8],
                vr.target_agent_id[:8],
                vr.verified,
            )

        # --------------------------------------------------------
        # Demo 2: Inject corrupted agent and watch consensus catch it
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Demo 2: Inject corrupted agent ---")
        log.info("=" * 60)

        corrupted = CorruptedFileReaderAgent(pool="filesystem")
        await runtime.registry.register(corrupted)
        await corrupted.start()
        await runtime._wire_agent(corrupted)

        log.info(
            "Injected corrupted agent: id=%s (disguised as file_reader)",
            corrupted.id[:8],
        )

        result = await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        consensus = result["consensus"]
        log.info(
            "Consensus: outcome=%s approval=%.3f votes=%d",
            consensus.outcome.value,
            consensus.approval_ratio,
            len(consensus.votes),
        )

        log.info("Verifications:")
        for vr in result["verifications"]:
            status_str = "PASS" if vr.verified else "FAIL"
            log.info(
                "  [%s] verifier=%s target=%s discrepancy=%s",
                status_str,
                vr.verifier_id[:8],
                vr.target_agent_id[:8],
                vr.discrepancy or "(none)",
            )

        failed = [v for v in result["verifications"] if not v.verified]
        log.info(
            "Red team caught %d discrepancies out of %d verifications",
            len(failed),
            len(result["verifications"]),
        )

        # --------------------------------------------------------
        # Demo 3: Trust network shows corrupted agent's trust is lower
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Demo 3: Trust network after corruption ---")
        log.info("=" * 60)

        trust_summary = runtime.trust_network.summary()
        for entry in trust_summary:
            agent_id = entry["agent_id"]
            is_corrupted = agent_id == corrupted.id
            label = " ** CORRUPTED **" if is_corrupted else ""
            log.info(
                "  agent=%s score=%.4f alpha=%.1f beta=%.1f uncertainty=%.4f%s",
                agent_id[:8],
                entry["score"],
                entry["alpha"],
                entry["beta"],
                entry["uncertainty"],
                label,
            )

        corrupted_score = runtime.trust_network.get_score(corrupted.id)
        log.info("Corrupted agent trust: %.4f (should be lower than honest agents)", corrupted_score)

        # --------------------------------------------------------
        # Demo 4: Hebbian agent-to-agent weights from verifications
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Demo 4: Agent-to-agent Hebbian weights ---")
        log.info("=" * 60)

        from probos.mesh.routing import REL_AGENT, REL_INTENT
        typed_weights = runtime.hebbian_router.all_weights_typed()
        intent_weights = {k: v for k, v in typed_weights.items() if k[2] == REL_INTENT}
        agent_weights = {k: v for k, v in typed_weights.items() if k[2] == REL_AGENT}

        log.info("Intent-to-agent weights: %d", len(intent_weights))
        log.info("Agent-to-agent weights: %d", len(agent_weights))
        for (src, tgt, rel), w in agent_weights.items():
            is_corrupted_tgt = tgt == corrupted.id
            label = " ** CORRUPTED TARGET **" if is_corrupted_tgt else ""
            log.info("  %s -> %s [%s]: %.4f%s", src[:8], tgt[:8], rel, w, label)

        # --------------------------------------------------------
        # Demo 5: Write with consensus
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Demo 5: Write file with consensus ---")
        log.info("=" * 60)

        # Create a writer pool
        await runtime.create_pool("writers", "file_writer", target_size=3)

        write_path = str(Path(tmp) / "consensus_written.txt")
        write_result = await runtime.submit_write_with_consensus(
            path=write_path,
            content="This file was written with consensus approval.\n",
            timeout=5.0,
        )

        log.info(
            "Write consensus: outcome=%s committed=%s",
            write_result["consensus"].outcome.value,
            write_result["committed"],
        )
        if write_result["committed"]:
            written_content = Path(write_path).read_text()
            log.info("  File content: %r", written_content)

        # --------------------------------------------------------
        # Demo 6: Event log with consensus events
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Demo 6: Event log (all categories) ---")
        log.info("=" * 60)

        total_events = await runtime.event_log.count()
        lifecycle_events = await runtime.event_log.count("lifecycle")
        mesh_events = await runtime.event_log.count("mesh")
        system_events = await runtime.event_log.count("system")
        consensus_events = await runtime.event_log.count("consensus")
        log.info(
            "Events: total=%d lifecycle=%d mesh=%d system=%d consensus=%d",
            total_events,
            lifecycle_events,
            mesh_events,
            system_events,
            consensus_events,
        )

        recent = await runtime.event_log.query(category="consensus", limit=10)
        for ev in recent:
            log.info(
                "  [%s] %s/%s agent=%s detail=%s",
                ev["timestamp"][11:19],
                ev["category"],
                ev["event"],
                (ev["agent_id"] or "")[:8],
                ev["detail"] or "",
            )

        # --------------------------------------------------------
        # Shutdown
        # --------------------------------------------------------
        log.info("")
        log.info("=" * 60)
        log.info("--- Shutting down ---")
        log.info("=" * 60)
        await runtime.stop()
        log.info("--- Done ---")


if __name__ == "__main__":
    asyncio.run(main())
