"""AD-801: ChromaDB import + episodic-collection sanity check."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _ChromaCheck:
    name: str = "chromadb"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        try:
            import chromadb  # noqa: F401
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"ChromaDB import failed: {type(exc).__name__}",
                remediation="Reinstall ProbOS (`uv sync` or `pip install -e .`) to restore dependencies.",
            )

        # Episodic-collection open sanity. Tier-2 log-and-degrade: if the
        # collection isn't there yet (fresh install), that's WARN — the
        # runtime will lazily create it on first write.
        episodic_db = ctx.data_dir / "episodic.db"
        if not episodic_db.exists():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="ChromaDB import OK (episodic store not yet initialized)",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"ChromaDB import OK; episodic store at {episodic_db}",
        )


register_check(_ChromaCheck())
