"""AD-742b: face-embedding identity recognition tests.

Mocks ``_compute_embedding`` to avoid loading facenet-pytorch's MTCNN/Resnet
in unit tests (slow + non-deterministic). Tests verify wiring + persistence +
cosine-distance + threshold logic + privacy invariants.

BF-286/287: real Pydantic config, no MagicMock at substrate boundary.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from probos.config import CognitiveConfig, PerceptionConfig
from probos.perception.identity import (
    EMBEDDING_DIM,
    IDENTITY_FILE_NAME,
    MODEL_ID,
    IdentityResolver,
    _cosine_distance,
)


# -- 1. Enrollment + persistence ----------------------------------------------


def test_resolver_not_enrolled_by_default(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    assert resolver.is_enrolled() is False


def test_enroll_persists_embedding(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    fake_embedding = [1.0] * EMBEDDING_DIM
    with patch.object(IdentityResolver, "_compute_embedding", return_value=fake_embedding):
        resolver.enroll(b"reference-image-bytes")
    identity_path = tmp_path / IDENTITY_FILE_NAME
    assert identity_path.is_file()
    payload = json.loads(identity_path.read_text(encoding="utf-8"))
    assert payload["embedding"] == fake_embedding
    assert payload["model_id"] == MODEL_ID
    assert payload["version"] == 1
    assert resolver.is_enrolled() is True


def test_enroll_no_face_raises(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    with patch.object(IdentityResolver, "_compute_embedding", return_value=None):
        with pytest.raises(ValueError, match="no face detected"):
            resolver.enroll(b"x")
    assert resolver.is_enrolled() is False


# -- 2. Revocation ------------------------------------------------------------


def test_revoke_removes_file(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    with patch.object(IdentityResolver, "_compute_embedding", return_value=[1.0] * EMBEDDING_DIM):
        resolver.enroll(b"x")
    assert resolver.revoke() is True
    assert resolver.is_enrolled() is False


def test_revoke_returns_false_when_not_enrolled(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    assert resolver.revoke() is False


# -- 3. Resolution --------------------------------------------------------


def test_resolve_returns_unknown_when_not_enrolled(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    assert resolver.resolve(b"x") == "unknown"


def test_resolve_returns_captain_when_below_threshold(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path, threshold=0.6)
    ref_emb = [1.0] * EMBEDDING_DIM
    with patch.object(IdentityResolver, "_compute_embedding", return_value=ref_emb):
        resolver.enroll(b"ref")
    # Same embedding -> cosine distance 0.0 -> "captain"
    with patch.object(IdentityResolver, "_compute_embedding", return_value=ref_emb):
        assert resolver.resolve(b"live") == "captain"


def test_resolve_returns_other_when_above_threshold(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path, threshold=0.6)
    with patch.object(IdentityResolver, "_compute_embedding", return_value=[1.0] * EMBEDDING_DIM):
        resolver.enroll(b"ref")
    # Opposite embedding -> cosine distance 2.0 -> "other"
    with patch.object(IdentityResolver, "_compute_embedding", return_value=[-1.0] * EMBEDDING_DIM):
        assert resolver.resolve(b"live") == "other"


def test_resolve_returns_unknown_when_live_face_not_found(tmp_path: Path) -> None:
    resolver = IdentityResolver(data_dir=tmp_path)
    with patch.object(IdentityResolver, "_compute_embedding", return_value=[1.0] * EMBEDDING_DIM):
        resolver.enroll(b"ref")
    with patch.object(IdentityResolver, "_compute_embedding", return_value=None):
        assert resolver.resolve(b"live") == "unknown"


def test_threshold_is_operator_tunable(tmp_path: Path) -> None:
    """Strict threshold (0.1) marks borderline as 'other'."""
    resolver = IdentityResolver(data_dir=tmp_path, threshold=0.1)
    ref_emb = [1.0] * EMBEDDING_DIM
    with patch.object(IdentityResolver, "_compute_embedding", return_value=ref_emb):
        resolver.enroll(b"ref")
    # Construct an embedding with cosine distance ~0.3 (between 0.1 and 0.6).
    # cos_dist = 1 - dot/(|a||b|). For a=[1]*N and b=[0.85]*half+[1]*half ...
    # simpler: use shifted embedding to produce non-zero distance.
    import math
    # a = [1]*512, b = [cos(theta)*1 ... shifted]. cos(theta) ~= 0.7 -> dist 0.3
    theta = 0.7  # radians
    live_emb = [math.cos(theta)] * EMBEDDING_DIM
    with patch.object(IdentityResolver, "_compute_embedding", return_value=live_emb):
        # distance = 1 - dot/(|a||b|) = 1 - (N*cos)/(sqrt(N)*sqrt(N*cos^2))
        #         = 1 - cos/abs(cos) = 0 (parallel vectors!)
        # So this gives distance 0; not what we want.
        # Use mixed-sign embedding instead.
        pass
    # Cleaner: ref = [1,0,0,...], live = [0.5, 0.866, 0, 0, ...] -> cos = 0.5 -> dist 0.5
    ref_emb2 = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    live_emb2 = [0.5, math.sqrt(1 - 0.25)] + [0.0] * (EMBEDDING_DIM - 2)
    # Re-enroll with explicit ref_emb2 (overwrites previous enrollment)
    with patch.object(IdentityResolver, "_compute_embedding", return_value=ref_emb2):
        resolver.enroll(b"ref")
    with patch.object(IdentityResolver, "_compute_embedding", return_value=live_emb2):
        # distance = 1 - 0.5 = 0.5 -> > 0.1 threshold -> "other"
        assert resolver.resolve(b"live") == "other"


# -- 4. Config fields ---------------------------------------------------------


def test_perception_config_identity_match_threshold_default() -> None:
    pc = PerceptionConfig()
    assert pc.identity_match_threshold == 0.6


def test_perception_config_identity_resolver_enabled_default() -> None:
    pc = PerceptionConfig()
    assert pc.identity_resolver_enabled is True


# -- 5. Cosine distance helper ------------------------------------------------


def test_cosine_distance_identical_vectors_is_zero() -> None:
    a = [1.0, 2.0, 3.0]
    assert _cosine_distance(a, a) == pytest.approx(0.0, abs=1e-9)


def test_cosine_distance_orthogonal_vectors_is_one() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_distance(a, b) == pytest.approx(1.0, abs=1e-9)


def test_cosine_distance_opposite_vectors_is_two() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert _cosine_distance(a, b) == pytest.approx(2.0, abs=1e-9)


def test_cosine_distance_zero_vector_returns_two() -> None:
    """Defensive: empty/zero vectors should not divide-by-zero."""
    assert _cosine_distance([0.0, 0.0], [1.0, 0.0]) == pytest.approx(2.0, abs=1e-9)


# -- 6. Privacy: reference photo not stored after enrollment ------------------


def test_enroll_only_persists_embedding_not_photo(tmp_path: Path) -> None:
    """AD-742b privacy invariant: only the embedding is on disk, not the photo."""
    resolver = IdentityResolver(data_dir=tmp_path)
    photo_bytes = b"PRIVATE_PHOTO_PAYLOAD_DO_NOT_PERSIST"
    with patch.object(IdentityResolver, "_compute_embedding", return_value=[1.0] * EMBEDDING_DIM):
        resolver.enroll(photo_bytes)
    # Walk the data_dir and assert no file contains the photo payload.
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert b"PRIVATE_PHOTO_PAYLOAD_DO_NOT_PERSIST" not in content, (
                f"reference photo bytes leaked into {path}"
            )


# -- 7. VisionConsumer integration -------------------------------------------


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {"sha-live": b"live-frame-bytes"}

    async def read(self, content_hash: str) -> bytes:
        return self.blobs.get(content_hash, b"")

    async def mime_for(self, content_hash: str) -> str:
        return "image/png"


class _StubResolver:
    """Drop-in test stub for IdentityResolver — no facenet load."""

    def __init__(self, *, enrolled: bool, label: str) -> None:
        self._enrolled = enrolled
        self._label = label
        self.calls: list[bytes] = []

    def is_enrolled(self) -> bool:
        return self._enrolled

    def resolve(self, image_bytes: bytes) -> str:
        self.calls.append(image_bytes)
        return self._label


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tier = ""
        self.model = ""
        self.tokens_used = 0
        self.cached = False
        self.error = ""
        self.request_id = "rid"


class _FakeLLMClient:
    def __init__(self) -> None:
        self.captured: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> Any:
        self.captured.append(request)
        return _FakeLLMResponse("captain")


class _FakeRuntime:
    def __init__(self) -> None:
        from probos.config import SystemConfig

        self.config = SystemConfig()
        self.llm_client = _FakeLLMClient()
        self._store = _FakeAttachmentStore()


def _install_store_patch(monkeypatch: pytest.MonkeyPatch, runtime: _FakeRuntime) -> None:
    from probos.routers import chat as _chat_mod

    def _get_store(rt: Any) -> Any:
        return rt._store

    monkeypatch.setattr(_chat_mod, "_get_attachment_store", _get_store)


def test_vision_consumer_uses_face_embedding_resolver_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an enrolled resolver is wired, identity goes through it and skips LLM."""
    from probos.perception.consumer import VisionConsumer

    runtime = _FakeRuntime()
    _install_store_patch(monkeypatch, runtime)

    consumer = VisionConsumer(runtime)
    stub = _StubResolver(enrolled=True, label="captain")
    consumer.set_identity_resolver(stub)

    result = asyncio.run(consumer._resolve_subject_identity("sha-live"))
    assert result == "captain"
    assert len(stub.calls) == 1
    # No LLM call for identity (the LLM-prompt path is bypassed).
    assert runtime.llm_client.captured == []


def test_vision_consumer_falls_back_to_unknown_when_resolver_not_enrolled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolver wired but not enrolled -> no LLM call, returns 'unknown'."""
    from probos.perception.consumer import VisionConsumer

    runtime = _FakeRuntime()
    _install_store_patch(monkeypatch, runtime)

    consumer = VisionConsumer(runtime)
    stub = _StubResolver(enrolled=False, label="unknown")
    consumer.set_identity_resolver(stub)

    result = asyncio.run(consumer._resolve_subject_identity("sha-live"))
    # No avatar ref set, no resolver enrolled -> "unknown"
    assert result == "unknown"
    # Resolver.resolve NOT called (gated on is_enrolled).
    assert stub.calls == []
