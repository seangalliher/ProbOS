"""AD-1326 (#1510): startup hands the dreaming engine the challenger the store's ledger makes possible.

``build_procedure_challenger`` and the engine's FIX sites are tested on their own. This is the seam between them:
``init_dreaming`` builds the service from the started ``ProcedureStore`` and passes it to ``DreamingEngine``, so a
production boot files FIX rewrites as challengers instead of superseding the champion at once.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from probos.cognitive.procedure_challenger import ProcedureChallenger
from probos.cognitive.procedure_store import ProcedureStore
from probos.config import DreamingConfig, SystemConfig
from probos.startup.dreaming import init_dreaming
from probos.startup.results import DreamingResult


class _Trust:
    """A boot with no trust records. Since BF-941, ``init_dreaming``'s cold-start detector reads none."""

    def raw_scores(self) -> dict[str, dict[str, float]]:
        return {}


async def _idle() -> None:
    await asyncio.sleep(3600)


async def _process(_text: str, **_kwargs: Any) -> None:
    return None


@asynccontextmanager
async def _booted(tmp_path: Path, config: SystemConfig) -> AsyncIterator[DreamingResult]:
    """``init_dreaming`` over a started real ``ProcedureStore``; its background tasks are stopped afterwards."""
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    result: DreamingResult | None = None
    try:
        result, _cold_start = await init_dreaming(
            config=config,
            trust_network=_Trust(),  # type: ignore[arg-type]
            hebbian_router=MagicMock(),
            episodic_memory=MagicMock(),
            pool_scaler=None,
            knowledge_store=None,
            registry=None,
            on_gap_predictions_fn=lambda _predictions: None,
            on_contradictions_fn=lambda _contradictions: None,
            on_post_dream_fn=lambda _report: None,
            on_pre_dream_fn=lambda: None,
            on_post_micro_dream_fn=lambda _report: None,
            process_natural_language_fn=_process,
            periodic_flush_loop_fn=_idle,
            refresh_emergent_detector_roster_fn=lambda: None,
            emit_event_fn=lambda _event_type, _payload: None,
            llm_client=MagicMock(),
            procedure_store=store,
        )
        yield result
    finally:
        if result is not None:
            await result.dream_scheduler.stop()
            await result.task_scheduler.stop()
            result.flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await result.flush_task
        await store.stop()


async def test_init_dreaming_gives_the_engine_a_challenger(tmp_path: Path) -> None:
    async with _booted(tmp_path, SystemConfig()) as result:
        assert isinstance(result.dreaming_engine._procedure_challenger, ProcedureChallenger)


async def test_init_dreaming_leaves_legacy_supersession_when_the_flag_is_off(tmp_path: Path) -> None:
    config = SystemConfig(dreaming=DreamingConfig(procedure_challenger_enabled=False))

    async with _booted(tmp_path, config) as result:
        assert result.dreaming_engine._procedure_challenger is None
