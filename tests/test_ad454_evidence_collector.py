"""AD-454: Tests for EvidenceCollector."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.cognitive.emergence_taxonomy import BehaviorCode
from probos.cognitive.evidence_collector import (
    EvidenceCollector,
    EvidenceObservation,
)
from probos.config import EmergenceCollectorConfig, SystemConfig
from probos.startup.finalize import _wire_emergence_collector
from probos.types import LLMRequest, LLMResponse


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakePost:
    body: str
    author_id: str
    author_callsign: str
    thread_id: str = "thr-1"
    id: str = "post-1"


class _FakeWardRoom:
    def __init__(self) -> None:
        self.posts: dict[str, dict[str, Any]] = {}
        self.threads: dict[str, dict[str, Any]] = {}

    async def get_post(self, post_id: str) -> dict[str, Any] | None:
        return self.posts.get(post_id)

    async def get_thread(
        self, thread_id: str, *, post_limit: int = 100
    ) -> dict[str, Any] | None:
        return self.threads.get(thread_id)


class _FakeLLMClient:
    """Stub that returns canned LLMResponse content."""

    def __init__(self, content: str | list[str] | None = None) -> None:
        self._content = content
        self._calls = 0
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, *, priority: Any = None) -> LLMResponse:
        self.requests.append(request)
        if self._content is None:
            return LLMResponse(content="", error="empty")
        if isinstance(self._content, list):
            content = self._content[min(self._calls, len(self._content) - 1)]
            self._calls += 1
        else:
            content = self._content
        return LLMResponse(content=content)


class _FailingLLMClient:
    async def complete(self, request: LLMRequest, *, priority: Any = None) -> LLMResponse:
        raise RuntimeError("simulated LLM outage")


@dataclass
class _FakeRuntime:
    llm_client: Any = None
    ward_room: Any = field(default_factory=_FakeWardRoom)
    listeners: list[tuple[Any, Any]] = field(default_factory=list)
    evidence_collector: Any = None

    def add_event_listener(self, fn: Any, event_types: Any = None) -> None:
        self.listeners.append((fn, event_types))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(
    tmp_path: Path,
    *,
    llm_content: str | list[str] | None = None,
    llm: Any = None,
    confidence_threshold: float = 0.7,
    dedup_window_seconds: float = 600.0,
    trial_id: str = "trial-1",
) -> tuple[EvidenceCollector, _FakeRuntime, _FakeWardRoom]:
    ward_room = _FakeWardRoom()
    if llm is None:
        llm = _FakeLLMClient(content=llm_content)
    runtime = _FakeRuntime(llm_client=llm, ward_room=ward_room)
    collector = EvidenceCollector(
        runtime=runtime,
        confidence_threshold=confidence_threshold,
        dedup_window_seconds=dedup_window_seconds,
        output_dir=tmp_path,
        llm_tier="fast",
        trial_id=trial_id,
        thread_context_limit=2,
        max_reasoning_chars=2000,
    )
    return collector, runtime, ward_room


def _seed_post(
    ward_room: _FakeWardRoom,
    *,
    post_id: str = "post-1",
    thread_id: str = "thr-1",
    author_id: str = "agent-a",
    author_callsign: str = "Vega",
    body: str = "I am directing Medical to standardize the protocol.",
) -> dict[str, Any]:
    post = {
        "id": post_id,
        "thread_id": thread_id,
        "author_id": author_id,
        "body": body,
        "author_callsign": author_callsign,
    }
    ward_room.posts[post_id] = post
    ward_room.threads.setdefault(thread_id, {"id": thread_id, "posts": []})
    return post


def _evt(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_id": post["id"],
        "thread_id": post["thread_id"],
        "author_id": post["author_id"],
        "author_callsign": post["author_callsign"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_post_happy_path_writes_obs_yaml(tmp_path: Path) -> None:
    llm_content = json.dumps({
        "codes": ["MGT-DIR"],
        "confidence": 0.9,
        "reasoning": "Direct chain-of-command directive.",
    })
    collector, _, ward_room = _make_collector(tmp_path, llm_content=llm_content)
    post = _seed_post(ward_room)

    obs = await collector.classify_post(
        post_id=post["id"], thread_id=post["thread_id"],
        author_id=post["author_id"], author_callsign=post["author_callsign"],
    )

    assert obs is not None
    assert obs.obs_id == "OBS-0001"
    target = tmp_path / "trial-1" / "OBS-0001.yaml"
    assert target.exists()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["obs_id"] == "OBS-0001"
    assert data["behavior_codes"] == ["MGT-DIR"]
    assert data["confidence"] == pytest.approx(0.9)
    assert data["author_callsign"] == "Vega"


@pytest.mark.asyncio
async def test_low_confidence_no_write(tmp_path: Path) -> None:
    llm_content = json.dumps({
        "codes": ["MGT-DIR"],
        "confidence": 0.3,
        "reasoning": "Maybe.",
    })
    collector, _, ward_room = _make_collector(tmp_path, llm_content=llm_content)
    post = _seed_post(ward_room)

    obs = await collector.classify_post(
        post_id=post["id"], thread_id=post["thread_id"],
        author_id=post["author_id"], author_callsign=post["author_callsign"],
    )

    assert obs is None
    trial_dir = tmp_path / "trial-1"
    assert not trial_dir.exists() or not list(trial_dir.glob("OBS-*.yaml"))


@pytest.mark.asyncio
async def test_dedup_within_window_drops_second(tmp_path: Path) -> None:
    llm_content = json.dumps({
        "codes": ["MGT-DIR"],
        "confidence": 0.9,
        "reasoning": "Directive.",
    })
    collector, _, ward_room = _make_collector(
        tmp_path, llm_content=llm_content, dedup_window_seconds=600.0
    )
    p1 = _seed_post(ward_room, post_id="p1")
    p2 = _seed_post(ward_room, post_id="p2", body="Another directive same author.")

    o1 = await collector.classify_post(
        post_id=p1["id"], thread_id=p1["thread_id"],
        author_id=p1["author_id"], author_callsign=p1["author_callsign"],
    )
    o2 = await collector.classify_post(
        post_id=p2["id"], thread_id=p2["thread_id"],
        author_id=p2["author_id"], author_callsign=p2["author_callsign"],
    )

    assert o1 is not None and o1.obs_id == "OBS-0001"
    assert o2 is None
    files = sorted((tmp_path / "trial-1").glob("OBS-*.yaml"))
    assert [f.name for f in files] == ["OBS-0001.yaml"]


@pytest.mark.asyncio
async def test_dedup_across_authors_does_not_dedup(tmp_path: Path) -> None:
    llm_content = json.dumps({
        "codes": ["MGT-DIR"],
        "confidence": 0.9,
        "reasoning": "Directive.",
    })
    collector, _, ward_room = _make_collector(tmp_path, llm_content=llm_content)
    p1 = _seed_post(
        ward_room, post_id="p1", author_id="agent-a", author_callsign="Vega",
    )
    p2 = _seed_post(
        ward_room, post_id="p2", author_id="agent-b", author_callsign="Bones",
    )

    o1 = await collector.classify_post(
        post_id=p1["id"], thread_id=p1["thread_id"],
        author_id=p1["author_id"], author_callsign=p1["author_callsign"],
    )
    o2 = await collector.classify_post(
        post_id=p2["id"], thread_id=p2["thread_id"],
        author_id=p2["author_id"], author_callsign=p2["author_callsign"],
    )

    assert o1 is not None and o1.obs_id == "OBS-0001"
    assert o2 is not None and o2.obs_id == "OBS-0002"
    files = sorted((tmp_path / "trial-1").glob("OBS-*.yaml"))
    assert [f.name for f in files] == ["OBS-0001.yaml", "OBS-0002.yaml"]


@pytest.mark.asyncio
async def test_anti_pattern_cascade_confab_is_persisted_and_flagged(
    tmp_path: Path,
) -> None:
    llm_content = json.dumps({
        "codes": ["CASCADE-CONFAB"],
        "confidence": 0.85,
        "reasoning": "Multiple agents misread the same telemetry event.",
    })
    collector, _, ward_room = _make_collector(tmp_path, llm_content=llm_content)
    post = _seed_post(ward_room)

    obs = await collector.classify_post(
        post_id=post["id"], thread_id=post["thread_id"],
        author_id=post["author_id"], author_callsign=post["author_callsign"],
    )

    assert obs is not None
    assert BehaviorCode.CASCADE_CONFAB in obs.behavior_codes
    target = tmp_path / "trial-1" / "OBS-0001.yaml"
    assert target.exists()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "CASCADE-CONFAB" in data["behavior_codes"]


def test_disabled_config_wirer_returns_false_and_no_listener_registered(
    tmp_path: Path,
) -> None:
    config = SystemConfig()
    assert config.emergence_collector.enabled is False
    runtime = _FakeRuntime(llm_client=_FakeLLMClient(), ward_room=_FakeWardRoom())

    result = _wire_emergence_collector(runtime=runtime, config=config)

    assert result is False
    assert runtime.listeners == []
    assert getattr(runtime, "evidence_collector", None) is None


@pytest.mark.asyncio
async def test_concurrent_posts_obs_numbers_monotonic_and_unique(
    tmp_path: Path,
) -> None:
    llm_content = json.dumps({
        "codes": ["MGT-DIR"],
        "confidence": 0.9,
        "reasoning": "Directive.",
    })
    collector, _, ward_room = _make_collector(
        tmp_path, llm_content=llm_content, dedup_window_seconds=0.0,
    )
    events: list[dict[str, Any]] = []
    for i in range(10):
        post = _seed_post(
            ward_room,
            post_id=f"p{i}",
            author_id=f"agent-{i}",
            author_callsign=f"AG{i}",
        )
        events.append(_evt(post))

    await asyncio.gather(*[collector.on_ward_room_post(evt) for evt in events])

    files = sorted((tmp_path / "trial-1").glob("OBS-*.yaml"))
    names = [f.name for f in files]
    assert names == [f"OBS-{i:04d}.yaml" for i in range(1, 11)]
    # No duplicates
    assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_llm_failure_logged_and_does_not_propagate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    collector, _, ward_room = _make_collector(tmp_path, llm=_FailingLLMClient())
    post = _seed_post(ward_room)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.evidence_collector"):
        # Direct invocation through the listener boundary — must not raise.
        await collector.on_ward_room_post(_evt(post))

    trial_dir = tmp_path / "trial-1"
    assert not trial_dir.exists() or not list(trial_dir.glob("OBS-*.yaml"))
    assert any("AD-454" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_malformed_llm_json_is_logged_and_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    collector, _, ward_room = _make_collector(
        tmp_path, llm_content="not json at all",
    )
    post = _seed_post(ward_room)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.evidence_collector"):
        obs = await collector.classify_post(
            post_id=post["id"], thread_id=post["thread_id"],
            author_id=post["author_id"], author_callsign=post["author_callsign"],
        )

    assert obs is None
    trial_dir = tmp_path / "trial-1"
    assert not trial_dir.exists() or not list(trial_dir.glob("OBS-*.yaml"))


@pytest.mark.asyncio
async def test_unknown_codes_filtered_and_skipped(tmp_path: Path) -> None:
    """LLM returns only unknown codes — collector treats as no codes and skips."""
    llm_content = json.dumps({
        "codes": ["NOT-A-CODE"],
        "confidence": 0.95,
        "reasoning": "irrelevant",
    })
    collector, _, ward_room = _make_collector(tmp_path, llm_content=llm_content)
    post = _seed_post(ward_room)

    obs = await collector.classify_post(
        post_id=post["id"], thread_id=post["thread_id"],
        author_id=post["author_id"], author_callsign=post["author_callsign"],
    )

    assert obs is None


@pytest.mark.asyncio
async def test_enabled_wirer_registers_listener(tmp_path: Path) -> None:
    """Happy-path wirer: cfg.enabled=True wires collector and listener."""
    config = SystemConfig()
    config.emergence_collector = EmergenceCollectorConfig(
        enabled=True,
        output_dir=str(tmp_path),
        trial_id="wired-trial",
    )
    runtime = _FakeRuntime(
        llm_client=_FakeLLMClient(content=json.dumps({
            "codes": ["MGT-DIR"], "confidence": 0.9, "reasoning": "x",
        })),
        ward_room=_FakeWardRoom(),
    )

    result = _wire_emergence_collector(runtime=runtime, config=config)

    assert result is True
    assert runtime.evidence_collector is not None
    assert isinstance(runtime.evidence_collector, EvidenceCollector)
    assert len(runtime.listeners) == 1
    fn, types = runtime.listeners[0]
    assert "ward_room_post_created" in [str(t) for t in types]
