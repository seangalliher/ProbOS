"""BF-666: force-describe cache expiry, identity, and race regressions."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

import probos.perception.consumer as consumer_module
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import AttachmentsConfig, PerceptionConfig, SystemConfig
from probos.perception.consumer import (
    VisionConsumer,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.supervisor import PerceptualHashStrategy, VisionSupervisor
from probos.perception.working_memory import VisionObservation
from probos.routers.chat import _get_attachment_store
from probos.types import IntentMessage, LLMResponse


_Candidate = tuple[str, float]


class _CountingStore:
    """Delegate to a real store while exposing public-call instrumentation."""

    def __init__(self, delegate: FilesystemAttachmentStore) -> None:
        self._delegate = delegate
        self._delegate_exists = delegate.exists
        self._delegate_read = delegate.read
        self._delegate_unlink = delegate.unlink
        self.exists_calls = 0
        self.read_calls = 0
        self.unlink_calls = 0
        self.exists_impl: Callable[[str], Awaitable[bool]] | None = None
        self.read_impl: Callable[[str], Awaitable[bytes]] | None = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(self._delegate, "exists", self.exists)
        monkeypatch.setattr(self._delegate, "read", self.read)
        monkeypatch.setattr(self._delegate, "unlink", self.unlink)

    async def passthrough_exists(self, content_hash: str) -> bool:
        return await self._delegate_exists(content_hash)

    async def exists(self, content_hash: str) -> bool:
        self.exists_calls += 1
        if self.exists_impl is not None:
            return await self.exists_impl(content_hash)
        return await self._delegate_exists(content_hash)

    async def read(self, content_hash: str) -> bytes:
        self.read_calls += 1
        if self.read_impl is not None:
            return await self.read_impl(content_hash)
        return await self._delegate_read(content_hash)

    async def unlink(self, content_hash: str) -> bool:
        self.unlink_calls += 1
        return await self._delegate_unlink(content_hash)


class _ObservedLock(asyncio.Lock):
    """Real asyncio lock with an event for the second acquire attempt."""

    def __init__(self) -> None:
        super().__init__()
        self.acquire_calls = 0
        self.peer_acquire_started = asyncio.Event()

    async def acquire(self) -> bool:
        self.acquire_calls += 1
        if self.locked():
            self.peer_acquire_started.set()
        return await super().acquire()


_RUNTIME_HARNESS_REFS: list[Any] = []


class _RuntimeHarness:
    """Real config/store substrate with service-boundary LLM/episode stubs."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        description: str = "A current frame.",
    ) -> None:
        self.config = SystemConfig()
        self.config.perception.enabled = True
        self.config.attachments.attachments_dir = str(tmp_path / "attachments")
        self.intent_bus = SimpleNamespace()
        self.episodic_memory = SimpleNamespace(
            store=AsyncMock(return_value=None),
        )
        self.llm_client = SimpleNamespace(
            complete=AsyncMock(
                return_value=LLMResponse(content=description, model="vision-fake")
            )
        )
        self.profile_store = None
        _RUNTIME_HARNESS_REFS.append(self)


@dataclass(frozen=True)
class _RaisingAttachmentsConfig:
    error_factory: Callable[[], BaseException]

    @property
    def attachments_dir(self) -> str:
        raise self.error_factory()


@dataclass(frozen=True)
class _ResolverFailureConfig:
    perception: PerceptionConfig
    attachments: _RaisingAttachmentsConfig


class _ResolverFailureRuntime:
    """Typed runtime whose public attachment configuration cannot resolve."""

    def __init__(self, error_factory: Callable[[], BaseException]) -> None:
        self.config = _ResolverFailureConfig(
            perception=PerceptionConfig(enabled=True),
            attachments=_RaisingAttachmentsConfig(error_factory),
        )
        self.episodic_memory = SimpleNamespace(store=AsyncMock(return_value=None))
        self.llm_client = SimpleNamespace(complete=AsyncMock())
        self.profile_store = None
        _RUNTIME_HARNESS_REFS.append(self)


@dataclass(frozen=True)
class _IncompleteRuntimeConfig:
    perception: object
    attachments: AttachmentsConfig


@dataclass(frozen=True)
class _IncompleteRuntime:
    config: _IncompleteRuntimeConfig


@dataclass(frozen=True)
class _MissingRetentionConfig:
    prompt_freshness_seconds: float = 0.0


@dataclass(frozen=True)
class _InvalidRetentionConfig:
    frame_retention_seconds: str = "invalid"
    prompt_freshness_seconds: float = 0.0


@dataclass(frozen=True)
class _MissingFreshnessConfig:
    frame_retention_seconds: float = 300.0


@dataclass(frozen=True)
class _InvalidFreshnessConfig:
    frame_retention_seconds: float = 300.0
    prompt_freshness_seconds: str = "invalid"


@dataclass(frozen=True)
class _ExplicitBoundsConfig:
    frame_retention_seconds: float
    prompt_freshness_seconds: float


@dataclass
class _FixedClock:
    now: float

    def time(self) -> float:
        return self.now


def _incomplete_consumer(
    tmp_path: Path,
    perception: object,
) -> tuple[_IncompleteRuntime, VisionConsumer]:
    runtime = _IncompleteRuntime(
        config=_IncompleteRuntimeConfig(
            perception=perception,
            attachments=AttachmentsConfig(
                attachments_dir=str(tmp_path / "attachments"),
            ),
        )
    )
    _RUNTIME_HARNESS_REFS.append(runtime)
    return runtime, VisionConsumer(runtime, min_interval_seconds=0.0)


def _make_jpeg(color: tuple[int, int, int] = (80, 120, 160)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def _store_frame(
    runtime: _RuntimeHarness,
    frame_bytes: bytes | None = None,
) -> tuple[FilesystemAttachmentStore, str, bytes]:
    blob = frame_bytes or _make_jpeg()
    sha = hashlib.sha256(blob).hexdigest()
    store = _get_attachment_store(runtime)
    assert isinstance(store, FilesystemAttachmentStore)
    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    return store, sha, blob


def _consumer(
    runtime: _RuntimeHarness,
    *,
    observer: bool = True,
    min_interval_seconds: float = 0.0,
    novelty_threshold: float = 0.15,
    baseline_max_age_seconds: float = 30.0,
) -> VisionConsumer:
    consumer = VisionConsumer(
        runtime,
        min_interval_seconds=min_interval_seconds,
        novelty_threshold=novelty_threshold,
        baseline_max_age_seconds=baseline_max_age_seconds,
    )
    if observer:
        consumer.register_observer("ezri")
    return consumer


@pytest.fixture(autouse=True)
def _reset_module_state() -> Any:
    reset_working_memories_for_tests()
    yield
    reset_working_memories_for_tests()


@pytest.mark.asyncio
async def test_stale_by_prompt_freshness_clears_all_aliases_without_store_or_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    runtime.config.perception.frame_retention_seconds = 300
    runtime.config.perception.prompt_freshness_seconds = 120.0
    consumer = _consumer(runtime)
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    candidate = ("a" * 64, time.time() - 121.0)
    consumer._latest_frame_by_session.update({"s1": candidate, "s2": candidate})
    consumer._latest_frame_global = candidate

    result = await consumer.force_describe_current_frame(session_id="s1")

    assert result is None
    assert consumer._select_latest_frame("s1") is None
    assert consumer._select_latest_frame("s2") is None
    assert counting.exists_calls == 0
    assert counting.read_calls == 0
    runtime.llm_client.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_freshness_disabled_uses_retention_bound(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="Within retention.")
    runtime.config.perception.frame_retention_seconds = 30
    runtime.config.perception.prompt_freshness_seconds = 0.0
    consumer = _consumer(runtime)
    _store, sha, _blob = await _store_frame(runtime)
    consumer.record_uploaded_frame(sha, "young", time.time() - 29.0)

    assert await consumer.force_describe_current_frame("young") == "Within retention."

    stale = ("b" * 64, time.time() - 31.0)
    consumer._latest_frame_by_session["old"] = stale
    consumer._latest_frame_global = stale
    before = runtime.llm_client.complete.await_count
    assert await consumer.force_describe_current_frame("old") is None
    assert runtime.llm_client.complete.await_count == before
    assert consumer._select_latest_frame("old") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("perception", "expected"),
    [
        pytest.param(_MissingRetentionConfig(), 300.0, id="missing-retention"),
        pytest.param(_InvalidRetentionConfig(), 300.0, id="invalid-retention"),
        pytest.param(_MissingFreshnessConfig(), 120.0, id="missing-freshness"),
        pytest.param(_InvalidFreshnessConfig(), 120.0, id="invalid-freshness"),
        pytest.param(
            _ExplicitBoundsConfig(
                frame_retention_seconds=240.0,
                prompt_freshness_seconds=0.0,
            ),
            240.0,
            id="zero-freshness-uses-retention",
        ),
        pytest.param(
            _ExplicitBoundsConfig(
                frame_retention_seconds=240.0,
                prompt_freshness_seconds=-1.0,
            ),
            240.0,
            id="negative-freshness-uses-retention",
        ),
    ],
)
async def test_force_describe_max_age_uses_typed_config_fallbacks(
    tmp_path: Path,
    perception: object,
    expected: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, consumer = _incomplete_consumer(tmp_path, perception)
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    clock = _FixedClock(now=10_000.0)
    monkeypatch.setattr(consumer_module, "time", clock)

    assert consumer._force_describe_max_age_seconds() == expected

    at_boundary: _Candidate = ("9" * 64, clock.now - expected)
    consumer.record_uploaded_frame(at_boundary[0], "boundary", at_boundary[1])
    assert await consumer.force_describe_current_frame("boundary") is None
    assert counting.exists_calls == 1
    assert counting.read_calls == 0

    epsilon_over: _Candidate = ("a" * 64, clock.now - expected - 0.000_001)
    consumer.record_uploaded_frame(epsilon_over[0], "over", epsilon_over[1])
    assert await consumer.force_describe_current_frame("over") is None
    assert counting.exists_calls == 1
    assert counting.read_calls == 0
    assert consumer._select_latest_frame("over") is None


@pytest.mark.asyncio
async def test_force_describe_age_boundary_is_strict_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, consumer = _incomplete_consumer(
        tmp_path,
        _ExplicitBoundsConfig(
            frame_retention_seconds=300.0,
            prompt_freshness_seconds=120.0,
        ),
    )
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    clock = _FixedClock(now=10_000.0)
    monkeypatch.setattr(consumer_module, "time", clock)

    at_boundary: _Candidate = ("b" * 64, clock.now - 120.0)
    consumer.record_uploaded_frame(at_boundary[0], "boundary", at_boundary[1])
    assert await consumer.force_describe_current_frame("boundary") is None
    assert counting.exists_calls == 1
    assert counting.read_calls == 0

    epsilon_over: _Candidate = ("c" * 64, clock.now - 120.000_001)
    consumer.record_uploaded_frame(epsilon_over[0], "over", epsilon_over[1])
    assert await consumer.force_describe_current_frame("over") is None
    assert counting.exists_calls == 1
    assert counting.read_calls == 0
    assert consumer._select_latest_frame("over") is None


@pytest.mark.asyncio
async def test_missing_preflight_clears_session_and_global_without_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    candidate = ("c" * 64, time.time())
    consumer._latest_frame_by_session["s1"] = candidate
    consumer._latest_frame_global = candidate

    with caplog.at_level(logging.WARNING):
        result = await consumer.force_describe_current_frame("s1")

    assert result is None
    assert consumer._select_latest_frame("s1") is None
    assert not caplog.records
    runtime.llm_client.complete.assert_not_awaited()
    assert get_or_create_working_memory("ezri").entries() == []


@pytest.mark.asyncio
async def test_second_call_after_missing_is_silent_noop_without_store_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    candidate = ("d" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)

    assert await consumer.force_describe_current_frame("s1") is None
    assert await consumer.force_describe_current_frame("s1") is None

    assert counting.exists_calls == 1
    assert counting.read_calls == 0
    runtime.llm_client.complete.assert_not_awaited()


def test_session_global_alias_clear_removes_all_matching_sessions_only(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    candidate = ("e" * 64, 10.0)
    survivor = ("f" * 64, 20.0)
    consumer._latest_frame_by_session.update(
        {"s1": candidate, "s2": candidate, "new": survivor}
    )
    consumer._latest_frame_global = candidate

    assert consumer._clear_latest_frame_if_matches(candidate) == 3
    assert consumer._latest_frame_by_session == {"new": survivor}
    assert consumer._latest_frame_global is None


@pytest.mark.asyncio
@pytest.mark.parametrize("same_sha", [False, True])
async def test_concurrent_newer_candidate_survives_missing_clear(
    tmp_path: Path,
    same_sha: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    old = ("1" * 64, time.time())
    consumer.record_uploaded_frame(old[0], "s1", old[1])
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _missing_after_barrier(_sha: str) -> bool:
        entered.set()
        await release.wait()
        return False

    counting.exists_impl = _missing_after_barrier
    task = asyncio.create_task(
        consumer.force_describe_current_frame("s1")
    )
    await entered.wait()
    newer_sha = old[0] if same_sha else "2" * 64
    newer = (newer_sha, old[1] + 1.0)
    consumer.record_uploaded_frame(newer[0], "s1", newer[1])
    release.set()
    assert await task is None

    assert consumer._select_latest_frame("s1") == newer
    assert consumer._select_latest_frame(None) == newer


@pytest.mark.asyncio
async def test_retention_toctou_exists_true_then_read_missing_clears_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    candidate = ("3" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)

    async def _exists(_sha: str) -> bool:
        return True

    async def _missing_read(_sha: str) -> bytes:
        raise FileNotFoundError(_sha)

    counting.exists_impl = _exists
    counting.read_impl = _missing_read
    wm = get_or_create_working_memory("ezri")
    prior = VisionObservation(
        timestamp=time.time() - 30.0,
        attachment_ref=candidate[0],
        description="Historical same-SHA observation.",
        novelty_score=0.2,
    )
    wm.append(prior)
    before = list(wm.entries())
    with caplog.at_level(logging.WARNING):
        assert await consumer.force_describe_current_frame("s1") is None
        assert await consumer.force_describe_current_frame("s1") is None

    assert counting.exists_calls == 2
    assert counting.read_calls == 1
    assert consumer._select_latest_frame("s1") is None
    assert wm.entries() == before
    assert not caplog.records


@pytest.mark.asyncio
async def test_post_process_reap_clears_original_candidate_without_undoing_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="Loaded before reap.")
    consumer = _consumer(runtime)
    real, sha, _blob = await _store_frame(runtime)
    captured_at = time.time()
    old = (sha, captured_at)
    consumer.record_uploaded_frame(sha, "s1", captured_at)
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    postcheck_entered = asyncio.Event()
    release_postcheck = asyncio.Event()

    async def _exists(content_hash: str) -> bool:
        if counting.exists_calls == 1:
            return True
        postcheck_entered.set()
        await release_postcheck.wait()
        return await counting.passthrough_exists(content_hash)

    counting.exists_impl = _exists
    task = asyncio.create_task(
        consumer.force_describe_current_frame("s1")
    )
    await postcheck_entered.wait()
    assert await counting.unlink(sha) is True
    newer = ("4" * 64, captured_at + 1.0)
    consumer.record_uploaded_frame(newer[0], "s1", newer[1])
    release_postcheck.set()

    assert await task is None
    entries = get_or_create_working_memory("ezri").entries()
    assert entries and entries[-1].attachment_ref == old[0]
    assert entries[-1].description == "Loaded before reap."
    assert consumer._select_latest_frame("s1") == newer
    assert consumer._select_latest_frame(None) == newer


@pytest.mark.asyncio
async def test_out_of_order_handle_cannot_regress_session_or_global_cache(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(
        runtime,
        min_interval_seconds=0.0,
        novelty_threshold=0.5,
        baseline_max_age_seconds=0.0,
    )
    frame = _make_jpeg()
    _store, sha, _ = await _store_frame(runtime, frame)
    newer = time.time()
    consumer.record_uploaded_frame(sha, "s1", newer)
    consumer._supervisor = VisionSupervisor(
        strategy=PerceptualHashStrategy(
            min_interval_seconds=0.0,
            novelty_threshold=0.5,
            baseline_max_age_seconds=0.0,
        )
    )
    consumer._supervisor.admit(frame)

    await consumer._handle(
        IntentMessage(
            intent="vision_observation",
            params={
                "attachment_ref": sha,
                "session_id": "s1",
                "captured_at": newer - 10.0,
            },
        )
    )

    assert consumer._select_latest_frame("s1") == (sha, newer)
    assert consumer._select_latest_frame(None) == (sha, newer)
    runtime.llm_client.complete.assert_not_awaited()


def test_older_other_session_updates_its_session_without_regressing_global(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    newest = ("5" * 64, 20.0)
    older = ("6" * 64, 10.0)
    consumer.record_uploaded_frame(newest[0], "new", newest[1])
    consumer.record_uploaded_frame(older[0], "old", older[1])

    assert consumer._select_latest_frame("old") == older
    assert consumer._select_latest_frame(None) == newest


def test_equal_captured_at_is_last_write_wins(tmp_path: Path) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    captured_at = 42.0
    consumer.record_uploaded_frame("7" * 64, "s1", captured_at)
    consumer.record_uploaded_frame("8" * 64, "s1", captured_at)

    expected = ("8" * 64, captured_at)
    assert consumer._select_latest_frame("s1") == expected
    assert consumer._select_latest_frame(None) == expected


@pytest.mark.asyncio
async def test_unexpected_exists_error_warns_and_preserves_candidate(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    candidate = ("9" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)

    async def _broken_exists(_sha: str) -> bool:
        raise OSError("backend unavailable")

    counting.exists_impl = _broken_exists
    with caplog.at_level(logging.WARNING):
        assert await consumer.force_describe_current_frame("s1") is None

    assert consumer._select_latest_frame("s1") == candidate
    assert counting.read_calls == 0
    assert len(caplog.records) == 1
    assert "preflight failed unexpectedly" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(lambda: FileNotFoundError("resolver path missing"), id="file-not-found"),
        pytest.param(lambda: OSError("resolver backend unavailable"), id="os-error"),
    ],
)
async def test_force_store_resolution_failure_warns_preserves_and_releases_lock(
    error_factory: Callable[[], BaseException],
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _ResolverFailureRuntime(error_factory)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    candidate = ("1" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])

    with caplog.at_level(logging.WARNING):
        result = await consumer.force_describe_current_frame("s1")

    assert result is None
    assert consumer._select_latest_frame("s1") == candidate
    assert len(caplog.records) == 1
    assert "attachment-store resolution failed unexpectedly" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None
    assert runtime.llm_client.complete.await_count == 0
    assert get_or_create_working_memory("ezri").entries() == []
    assert consumer._force_describe_lock.locked() is False
    async with consumer._force_describe_permit() as acquired:
        assert acquired is True


@pytest.mark.asyncio
async def test_process_store_resolution_failure_warns_and_preserves_candidate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _ResolverFailureRuntime(lambda: OSError("resolver backend unavailable"))
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    candidate = ("2" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])

    with caplog.at_level(logging.WARNING):
        result = await consumer._process(
            IntentMessage(
                intent="vision_observation",
                params={
                    "attachment_ref": candidate[0],
                    "session_id": "s1",
                    "captured_at": candidate[1],
                },
            ),
            cache_candidate=candidate,
        )

    assert result is None
    assert consumer._select_latest_frame("s1") == candidate
    assert len(caplog.records) == 1
    assert "attachment-store resolution failed unexpectedly" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None
    assert runtime.llm_client.complete.await_count == 0
    assert get_or_create_working_memory("ezri").entries() == []


@pytest.mark.asyncio
async def test_force_store_resolution_cancellation_propagates_and_releases_lock() -> None:
    runtime = _ResolverFailureRuntime(asyncio.CancelledError)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    candidate = ("3" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])

    with pytest.raises(asyncio.CancelledError):
        await consumer.force_describe_current_frame("s1")

    assert consumer._select_latest_frame("s1") == candidate
    assert consumer._force_describe_lock.locked() is False
    async with consumer._force_describe_permit() as acquired:
        assert acquired is True


@pytest.mark.asyncio
async def test_process_store_resolution_cancellation_propagates_and_preserves_candidate() -> None:
    runtime = _ResolverFailureRuntime(asyncio.CancelledError)
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    candidate = ("4" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])

    with pytest.raises(asyncio.CancelledError):
        await consumer._process(
            IntentMessage(
                intent="vision_observation",
                params={
                    "attachment_ref": candidate[0],
                    "session_id": "s1",
                    "captured_at": candidate[1],
                },
            ),
            cache_candidate=candidate,
        )

    assert consumer._select_latest_frame("s1") == candidate
    assert runtime.llm_client.complete.await_count == 0
    assert get_or_create_working_memory("ezri").entries() == []


@pytest.mark.asyncio
async def test_unexpected_read_error_warns_and_preserves_candidate(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    candidate = ("a" * 64, time.time())
    consumer.record_uploaded_frame(candidate[0], "s1", candidate[1])
    real = _get_attachment_store(runtime)
    assert isinstance(real, FilesystemAttachmentStore)
    counting = _CountingStore(real)
    counting.install(monkeypatch)

    async def _exists(_sha: str) -> bool:
        return True

    async def _broken_read(_sha: str) -> bytes:
        raise OSError("read backend unavailable")

    counting.exists_impl = _exists
    counting.read_impl = _broken_read
    wm = get_or_create_working_memory("ezri")
    prior = VisionObservation(
        timestamp=time.time() - 30.0,
        attachment_ref=candidate[0],
        description="Historical same-SHA observation.",
        novelty_score=0.2,
    )
    wm.append(prior)
    before = list(wm.entries())
    with caplog.at_level(logging.WARNING):
        assert await consumer.force_describe_current_frame("s1") is None

    assert consumer._select_latest_frame("s1") == candidate
    assert wm.entries() == before
    assert len(caplog.records) == 1
    assert "read failed unexpectedly" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None


@pytest.mark.asyncio
async def test_empty_llm_does_not_return_historical_same_sha_observation(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="")
    consumer = _consumer(runtime)
    _store, sha, _blob = await _store_frame(runtime)
    candidate = (sha, time.time())
    consumer.record_uploaded_frame(sha, "s1", candidate[1])
    wm = get_or_create_working_memory("ezri")
    prior = VisionObservation(
        timestamp=time.time() - 30.0,
        attachment_ref=sha,
        description="Historical same-SHA observation.",
        novelty_score=0.2,
    )
    wm.append(prior)
    before = list(wm.entries())

    result = await consumer.force_describe_current_frame("s1")

    assert result is None
    assert wm.entries() == before
    assert consumer._select_latest_frame("s1") == candidate
    assert runtime.llm_client.complete.await_count == 1


@pytest.mark.asyncio
async def test_unexpected_postcheck_error_warns_preserves_and_returns_description(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="Completed before postcheck error.")
    consumer = _consumer(runtime)
    real, sha, _blob = await _store_frame(runtime)
    candidate = (sha, time.time())
    consumer.record_uploaded_frame(sha, "s1", candidate[1])
    counting = _CountingStore(real)
    counting.install(monkeypatch)

    async def _exists_then_error(content_hash: str) -> bool:
        if counting.exists_calls == 1:
            return await counting.passthrough_exists(content_hash)
        raise OSError("postcheck backend unavailable")

    counting.exists_impl = _exists_then_error
    with caplog.at_level(logging.WARNING):
        result = await consumer.force_describe_current_frame("s1")

    assert result == "Completed before postcheck error."
    assert consumer._select_latest_frame("s1") == candidate
    assert len(caplog.records) == 1
    assert "postcheck failed unexpectedly" in caplog.records[0].message
    assert caplog.records[0].exc_info is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at", ["preflight", "process"])
async def test_force_describe_cancellation_propagates_and_preserves_candidate(
    tmp_path: Path,
    cancel_at: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    real, sha, _blob = await _store_frame(runtime)
    candidate = (sha, time.time())
    consumer.record_uploaded_frame(sha, "s1", candidate[1])
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    entered = asyncio.Event()
    blocker = asyncio.Event()

    if cancel_at == "preflight":
        async def _blocking_exists(_sha: str) -> bool:
            entered.set()
            await blocker.wait()
            return True

        counting.exists_impl = _blocking_exists
    else:
        async def _blocking_process(
            _msg: IntentMessage,
            *,
            cache_candidate: _Candidate | None = None,
        ) -> VisionObservation | None:
            assert cache_candidate == candidate
            entered.set()
            await blocker.wait()
            return None

        consumer._process = _blocking_process  # type: ignore[method-assign]

    task = asyncio.create_task(
        consumer.force_describe_current_frame("s1")
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert consumer._select_latest_frame("s1") == candidate
    assert consumer._force_describe_lock.locked() is False
    async with consumer._force_describe_permit() as acquired:
        assert acquired is True
    current = asyncio.current_task()
    assert current is not None
    assert all(task.done() for task in asyncio.all_tasks() if task is not current)


@pytest.mark.asyncio
async def test_post_process_exists_cancellation_preserves_candidate_and_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="Produced before cancellation.")
    consumer = _consumer(runtime)
    real, sha, _blob = await _store_frame(runtime)
    candidate = (sha, time.time())
    consumer.record_uploaded_frame(sha, "s1", candidate[1])
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    postcheck_entered = asyncio.Event()
    blocker = asyncio.Event()

    async def _exists(content_hash: str) -> bool:
        if counting.exists_calls == 1:
            return await counting.passthrough_exists(content_hash)
        postcheck_entered.set()
        await blocker.wait()
        return True

    counting.exists_impl = _exists
    task = asyncio.create_task(consumer.force_describe_current_frame("s1"))
    await postcheck_entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.done()
    assert consumer._select_latest_frame("s1") == candidate
    assert consumer._force_describe_lock.locked() is False
    async with consumer._force_describe_permit() as acquired:
        assert acquired is True
    assert counting.exists_calls == 2
    assert counting.read_calls == 2
    current = asyncio.current_task()
    assert current is not None
    assert all(pending.done() for pending in asyncio.all_tasks() if pending is not current)


@pytest.mark.asyncio
async def test_handle_process_cancellation_propagates_and_preserves_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    real, sha, _blob = await _store_frame(runtime)
    entered = asyncio.Event()
    blocker = asyncio.Event()

    async def _blocking_read(_sha: str) -> bytes:
        entered.set()
        await blocker.wait()
        return b"never"

    counting = _CountingStore(real)
    counting.read_impl = _blocking_read
    counting.install(monkeypatch)
    task = asyncio.create_task(
        consumer._handle(
            IntentMessage(
                intent="vision_observation",
                params={
                    "attachment_ref": sha,
                    "session_id": "s1",
                    "captured_at": time.time(),
                },
            )
        )
    )
    await entered.wait()
    candidate = consumer._select_latest_frame("s1")
    assert candidate is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert consumer._select_latest_frame("s1") == candidate


@pytest.mark.asyncio
async def test_stale_camera_off_candidate_cannot_reanimate_working_memory(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    runtime.config.perception.prompt_freshness_seconds = 120.0
    consumer = _consumer(runtime)
    wm = get_or_create_working_memory("ezri")
    old_description = "A scene from yesterday."
    wm.append(
        VisionObservation(
            timestamp=time.time() - 3600.0,
            attachment_ref="b" * 64,
            description=old_description,
            novelty_score=0.5,
        )
    )
    consumer.record_uploaded_frame("c" * 64, "s1", time.time() - 121.0)
    before = list(wm.entries())

    assert await consumer.force_describe_current_frame("s1") is None
    assert wm.entries() == before
    rendered = wm.render_for_prompt(freshness_s=120.0)
    assert "Camera not active" in rendered
    assert old_description not in rendered
    runtime.llm_client.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_uploaded_frame_after_eviction_restores_force_describe(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="Fresh upload restored.")
    consumer = _consumer(runtime)
    consumer.record_uploaded_frame("d" * 64, "s1", time.time())
    assert await consumer.force_describe_current_frame("s1") is None

    _store, sha, _blob = await _store_frame(runtime, _make_jpeg((20, 40, 60)))
    captured_at = time.time()
    consumer.record_uploaded_frame(sha, "s1", captured_at)

    assert await consumer.force_describe_current_frame("s1") == "Fresh upload restored."
    assert consumer._select_latest_frame("s1") == (sha, captured_at)
    assert consumer._select_latest_frame(None) == (sha, captured_at)


@pytest.mark.asyncio
async def test_fresh_low_novelty_frame_remains_cached_without_llm(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(
        runtime,
        min_interval_seconds=0.0,
        novelty_threshold=0.5,
        baseline_max_age_seconds=0.0,
    )
    frame = _make_jpeg((50, 50, 50))
    _store, sha, _blob = await _store_frame(runtime, frame)
    consumer._supervisor = VisionSupervisor(
        strategy=PerceptualHashStrategy(
            min_interval_seconds=0.0,
            novelty_threshold=0.5,
            baseline_max_age_seconds=0.0,
        )
    )
    consumer._supervisor.admit(frame)
    captured_at = time.time()

    await consumer._handle(
        IntentMessage(
            intent="vision_observation",
            params={
                "attachment_ref": sha,
                "session_id": "s1",
                "captured_at": captured_at,
            },
        )
    )

    assert consumer._select_latest_frame("s1") == (sha, captured_at)
    assert consumer._select_latest_frame(None) == (sha, captured_at)
    runtime.llm_client.complete.assert_not_awaited()
    assert consumer.recent_decisions()[0]["reason"] == "low_novelty"


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", [None, ""])
async def test_empty_cache_with_none_or_empty_session_is_silent_noop(
    tmp_path: Path,
    session_id: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    with caplog.at_level(logging.WARNING):
        assert await consumer.force_describe_current_frame(session_id) is None
    assert not caplog.records
    runtime.llm_client.complete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", [None, "missing"])
async def test_none_session_and_missing_requested_session_preserve_global_fallback(
    tmp_path: Path,
    session_id: str | None,
) -> None:
    runtime = _RuntimeHarness(tmp_path, description="Global fallback.")
    consumer = _consumer(runtime)
    _store, sha, _blob = await _store_frame(runtime)
    captured_at = time.time()
    consumer.record_uploaded_frame(sha, "origin", captured_at)

    assert await consumer.force_describe_current_frame(session_id) == "Global fallback."


@pytest.mark.asyncio
async def test_concurrent_force_calls_drop_second_before_store_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    observed_lock = _ObservedLock()
    consumer._force_describe_lock = observed_lock
    real, sha, _blob = await _store_frame(runtime)
    consumer.record_uploaded_frame(sha, "s1", time.time())
    counting = _CountingStore(real)
    counting.install(monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _blocking_exists(content_hash: str) -> bool:
        entered.set()
        await release.wait()
        return await counting.passthrough_exists(content_hash)

    counting.exists_impl = _blocking_exists
    first = asyncio.create_task(consumer.force_describe_current_frame("s1"))
    await entered.wait()
    second = asyncio.create_task(consumer.force_describe_current_frame("s1"))
    second_result = await asyncio.wait_for(second, timeout=0.1)
    assert second_result is None
    assert counting.exists_calls == 1
    assert counting.read_calls == 0
    runtime.llm_client.complete.assert_not_awaited()

    observed_lock.peer_acquire_started.clear()

    async def _wait_for_permit() -> bool:
        async with consumer._force_describe_permit() as acquired:
            return acquired

    waiter = asyncio.create_task(_wait_for_permit())
    await observed_lock.peer_acquire_started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert consumer._force_describe_lock.locked() is True

    release.set()
    await first
    assert consumer._force_describe_lock.locked() is False
    assert counting.exists_calls == 2
    assert counting.read_calls == 2
    assert runtime.llm_client.complete.await_count == 1


@pytest.mark.asyncio
async def test_handle_without_captured_at_uses_one_exact_fallback_candidate_for_missing_clear(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    sha = "e" * 64
    with caplog.at_level(logging.WARNING):
        await consumer._handle(
            IntentMessage(
                intent="vision_observation",
                params={"attachment_ref": sha, "session_id": "s1"},
            )
        )

    assert consumer._select_latest_frame("s1") is None
    assert consumer._select_latest_frame(None) is None
    assert not caplog.records
    runtime.llm_client.complete.assert_not_awaited()


def test_non_finite_captured_at_cannot_poison_cache_ordering(
    tmp_path: Path,
) -> None:
    runtime = _RuntimeHarness(tmp_path)
    consumer = _consumer(runtime)
    good = ("f" * 64, time.time())
    consumer.record_uploaded_frame(good[0], "s1", good[1])

    for value in (math.nan, math.inf, -math.inf):
        consumer.record_uploaded_frame("0" * 64, "s1", value)
    for value in (None, "not-a-time"):
        consumer.record_uploaded_frame("0" * 64, "s1", value)  # type: ignore[arg-type]

    selected = consumer._select_latest_frame("s1")
    assert selected == good
    assert selected is not None and math.isfinite(selected[1])
    assert consumer._select_latest_frame(None) == good
