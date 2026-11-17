"""The DM camera hook answers by its deadline whichever step is slow, and the DM route times a send that raises (#1808).

``VisionConsumer.force_describe_current_frame`` bounded only its describe step: the storage checks before and after
it could hold the DM route and the group round without limit. Its steps now run in a task of their own and the
caller waits for that task with one deadline. The DM route's timing line is written in a ``finally``.

Synthetic fixtures only. A store that never answers blocks on an event the test sets only when it cleans up, so the
base never returns and the bound below tells the base from the build however loaded the host is. Until M2 the cases
marked ``built`` are strict expected failures: each fails on the base at its own assert. M2 makes ``built`` a no-op.
The unmarked cases are controls that pass on the base and after.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.mesh.intent import IntentAuthorizationDenied
from probos.perception.consumer import (
    VisionConsumer,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.chat import _ATTACHMENT_STORE_CACHE, _get_attachment_store
from probos.types import IntentMessage, LLMResponse
from tests.test_bf932_reply_path_timing import _ROUTE, _dm, _field, _lines, _runtime

# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1808: the hook bounds only its describe step until M2")

_DEADLINE = 0.2  # the timeout_s each bounded call passes
_BOUND = 3.0  # how long a test waits for a call before it fails; generous for a loaded host
_THREAD_CAP = 30.0  # a gated store thread gives up after this, so a failing test strands no thread
_TIMED_OUT = "force_describe timed out"
_DESCRIPTION = "A current frame."


@pytest.fixture(autouse=True)
def _reset_module_state() -> Any:
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()
    yield
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


def _vision_runtime(tmp_path: Path) -> SimpleNamespace:
    """Real config and attachment store; the vision model and the episode store are service-level stubs."""
    config = SystemConfig()
    config.perception.enabled = True
    config.attachments.attachments_dir = str(tmp_path / "attachments")
    return SimpleNamespace(
        config=config,
        intent_bus=SimpleNamespace(),
        episodic_memory=SimpleNamespace(store=AsyncMock(return_value=None)),
        llm_client=SimpleNamespace(
            complete=AsyncMock(return_value=LLMResponse(content=_DESCRIPTION, model="vision-fake")),
        ),
        profile_store=None,
    )


def _consumer(runtime: SimpleNamespace) -> VisionConsumer:
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    return consumer


async def _frame(
    runtime: SimpleNamespace, consumer: VisionConsumer,
) -> tuple[FilesystemAttachmentStore, str, float]:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=(80, 120, 160)).save(buf, "JPEG", quality=80)
    blob = buf.getvalue()
    sha = hashlib.sha256(blob).hexdigest()
    store = _get_attachment_store(runtime)
    assert isinstance(store, FilesystemAttachmentStore)
    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    captured_at = time.time()
    consumer.record_uploaded_frame(sha, "s1", captured_at)
    return store, sha, captured_at


def _timed_out(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and _TIMED_OUT in r.getMessage()
    ]


async def _settle(*tasks: asyncio.Task[Any]) -> None:
    """End the test's own calls: wait up to the bound, then cancel what is left."""
    if not tasks:
        return
    _done, pending = await asyncio.wait(tasks, timeout=_BOUND)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _permit_free(consumer: VisionConsumer) -> bool:
    deadline = time.monotonic() + _BOUND
    while consumer._force_describe_lock.locked() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    return not consumer._force_describe_lock.locked()


def _others_done() -> bool:
    current = asyncio.current_task()
    return all(task.done() for task in asyncio.all_tasks() if task is not current)


class _GatedRoot:
    """The store's root, except that ``glob`` blocks in the store's own thread until the test opens the gate."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.calls = 0

    def glob(self, pattern: str) -> Any:
        self.calls += 1
        self.entered.set()
        self.gate.wait(_THREAD_CAP)
        return self._root.glob(pattern)


@built
@pytest.mark.asyncio
async def test_t1_preflight_store_that_never_answers_returns_none_by_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills R0 (the base bounds only ``_process``), MU1 and MU3."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, _sha, _captured_at = await _frame(runtime, consumer)
    never = asyncio.Event()

    async def _exists(_content_hash: str) -> bool:
        await never.wait()
        return True

    monkeypatch.setattr(store, "exists", _exists)
    caplog.set_level(logging.WARNING)
    call = asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE))
    try:
        done, _pending = await asyncio.wait((call,), timeout=_BOUND)
        assert call in done, "the call still waits on the storage pre-check"
        assert call.result() is None
        lines = _timed_out(caplog)
        assert len(lines) == 1 and "step=preflight" in lines[0], lines
        runtime.llm_client.complete.assert_not_awaited()
    finally:
        never.set()
        await _settle(call)


@built
@pytest.mark.asyncio
async def test_t2_postcheck_store_that_never_answers_returns_none_and_keeps_the_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills R0, MU1 and MU4. The observation written before the post-check stays in working memory."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, sha, captured_at = await _frame(runtime, consumer)
    real_exists = store.exists
    exists_calls: list[str] = []
    never = asyncio.Event()

    async def _exists(content_hash: str) -> bool:
        exists_calls.append(content_hash)
        if len(exists_calls) == 1:
            return await real_exists(content_hash)
        await never.wait()
        return True

    observation = VisionObservation(
        timestamp=time.time(),
        attachment_ref=sha,
        description="Written before the post-check.",
        novelty_score=1.0,
        session_id="s1",
    )

    async def _process(
        _msg: IntentMessage, *, cache_candidate: tuple[str, float] | None = None,
    ) -> VisionObservation:
        assert cache_candidate == (sha, captured_at)
        get_or_create_working_memory("ezri").append(observation)
        return observation

    monkeypatch.setattr(store, "exists", _exists)
    monkeypatch.setattr(consumer, "_process", _process)
    caplog.set_level(logging.WARNING)
    call = asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE))
    try:
        done, _pending = await asyncio.wait((call,), timeout=_BOUND)
        assert call in done, "the call still waits on the storage post-check"
        assert call.result() is None
        assert len(exists_calls) == 2
        lines = _timed_out(caplog)
        assert len(lines) == 1 and "step=postcheck" in lines[0], lines
        kept = [e.description for e in get_or_create_working_memory("ezri").entries()]
        assert kept == ["Written before the post-check."]
    finally:
        never.set()
        await _settle(call)


@built
@pytest.mark.asyncio
async def test_t3_store_thread_that_never_returns_does_not_hold_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills R0, MU1, MU2 and MU3. The real store waits for its own thread after a cancellation, so only a
    caller that does not await its cancelled step returns by the deadline; the step keeps the permit meanwhile."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, _sha, _captured_at = await _frame(runtime, consumer)
    gated = _GatedRoot(store._root)
    monkeypatch.setattr(store, "_root", gated)
    caplog.set_level(logging.WARNING)
    calls: list[asyncio.Task[Any]] = []
    try:
        calls.append(asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE)))
        done, _pending = await asyncio.wait((calls[0],), timeout=_BOUND)
        assert calls[0] in done, "the call still waits on the store's thread"
        assert calls[0].result() is None
        lines = _timed_out(caplog)
        assert len(lines) == 1 and "step=preflight" in lines[0], lines
        assert await asyncio.to_thread(gated.entered.wait, _BOUND)
        calls.append(asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE)))
        done, _pending = await asyncio.wait((calls[1],), timeout=_BOUND)
        assert calls[1] in done and calls[1].result() is None
        assert gated.calls == 1
        gated.gate.set()
        assert await _permit_free(consumer), "the permit outlived the store's thread"
    finally:
        gated.gate.set()
        await _settle(*calls)
        store.close()


@built
@pytest.mark.asyncio
async def test_t4_denied_send_writes_one_route_line_with_sent_raised(caplog: pytest.LogCaptureFixture) -> None:
    """Kills R0b (the base writes the line only after a send that returns), MU7 and MU8."""
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    runtime = _runtime([])
    denial = IntentAuthorizationDenied("direct_message", "test-hook", "send")
    runtime.intent_bus.send = AsyncMock(side_effect=denial)
    with pytest.raises(IntentAuthorizationDenied) as raised:
        await _dm(runtime)
    assert raised.value is denial
    lines = _lines(caplog, _ROUTE)
    assert len(lines) == 1, lines
    assert _field(lines[0], "sent") == "raised"
    assert _field(lines[0], "hook") == "ran"
    assert float(_field(lines[0], "send_ms")) >= 0.0


@pytest.mark.asyncio
async def test_t5_describe_inside_the_deadline_returns_its_description(tmp_path: Path) -> None:
    """Control (passes on the base). Kills MU9."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    await _frame(runtime, consumer)
    assert await consumer.force_describe_current_frame("s1", timeout_s=5.0) == _DESCRIPTION


@pytest.mark.asyncio
async def test_t6_cancelled_caller_waits_for_the_store_thread_then_frees_the_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control (passes on the base). Kills MU5: a cancelled caller cancels its task and waits for it, so the
    permit is free and no task is left when the caller's cancellation surfaces."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, _sha, _captured_at = await _frame(runtime, consumer)
    gated = _GatedRoot(store._root)
    monkeypatch.setattr(store, "_root", gated)
    caller = asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_THREAD_CAP))
    try:
        assert await asyncio.to_thread(gated.entered.wait, _BOUND)
        caller.cancel()
        done, _pending = await asyncio.wait((caller,), timeout=0.3)
        assert caller not in done, "the cancelled caller left before its store thread ended"
        gated.gate.set()
        done, _pending = await asyncio.wait((caller,), timeout=_BOUND)
        assert caller in done and caller.cancelled()
        assert consumer._force_describe_lock.locked() is False
        assert _others_done()
    finally:
        gated.gate.set()
        await _settle(caller)
        store.close()
