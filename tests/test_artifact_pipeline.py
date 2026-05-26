"""AD-797 (Wave 197): tests for DmReplyPipeline.step_4f_extract_artifacts."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from probos.artifacts import ArtifactStore
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def write(
        self, content_hash: str, blob: bytes, mime: str,
        *, origin: str = "chat_attachment",
    ) -> Path:
        self._blobs[content_hash] = blob
        return Path("/fake") / content_hash


class _FakeRuntime:
    def __init__(self, tmp_path: Path) -> None:
        self.artifact_store = ArtifactStore(tmp_path / "artifacts.db")
        self.attachment_store = _FakeAttachmentStore()
        self.config = type("Cfg", (), {})()
        self.config.cognitive = type(
            "Cog", (), {"artifact_fenced_threshold_lines": 40},
        )()


def _make_ctx(runtime: _FakeRuntime, response_text: str) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=type("A", (), {"agent_type": "test"})(),
        agent_id="agent-1",
        callsign="Tester",
        req_message="hi",
        response_text=response_text,
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="hi",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="thread-xyz",
    )


def test_reply_with_artifact_tag_persists_and_stubs_body(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    body = (
        "Sure, here is the file:\n"
        '<artifact name="hello.md" mime="text/markdown">\n'
        "# Hello\n\nWorld\n"
        "</artifact>\n"
        "Anything else?"
    )
    ctx = _make_ctx(runtime, body)
    pipeline = DmReplyPipeline(ctx)

    asyncio.run(pipeline.step_4f_extract_artifacts())

    # Body now has the stub line, original block gone.
    assert "<artifact" not in ctx.response_text
    assert "# Hello" not in ctx.response_text
    assert "[Artifact: hello.md v1 - 3 lines, text/markdown]" in ctx.response_text

    # ArtifactStore has the row.
    rows = runtime.artifact_store.list_thread_latest("thread-xyz")
    assert len(rows) == 1
    assert rows[0].name == "hello.md"

    # AttachmentStore has the bytes.
    expected_hash = hashlib.sha256(b"# Hello\n\nWorld").hexdigest()
    assert expected_hash in runtime.attachment_store._blobs


def test_extractor_failure_falls_through_with_original_response_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _FakeRuntime(tmp_path)
    body = (
        '<artifact name="x.md" mime="text/markdown">\n'
        "boom\n"
        "</artifact>\n"
    )
    ctx = _make_ctx(runtime, body)
    pipeline = DmReplyPipeline(ctx)

    def _explode(*a, **kw):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(
        "probos.cognitive.dm.artifact_extractor.extract_artifacts",
        _explode,
    )
    # Pipeline-internal exception → response_text left intact.
    asyncio.run(pipeline.step_4f_extract_artifacts())
    assert ctx.response_text == body


def test_no_thread_id_is_noop(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    body = (
        '<artifact name="z.md" mime="text/markdown">\n'
        "ignored\n"
        "</artifact>\n"
    )
    ctx = _make_ctx(runtime, body)
    ctx.chat_thread_id = ""  # no thread → bail
    pipeline = DmReplyPipeline(ctx)

    asyncio.run(pipeline.step_4f_extract_artifacts())
    # Body unchanged, no artifact stored.
    assert ctx.response_text == body
    assert runtime.artifact_store.list_thread_latest("") == []
