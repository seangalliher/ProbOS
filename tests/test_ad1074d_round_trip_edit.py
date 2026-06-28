"""AD-1074d (Cowork epic #1010): round-trip editing of a workspace document.

Substrate-honest: a REAL ``SubprocessSandbox`` runs actual Python and a REAL
``ArtifactStore`` + a Protocol-faithful ``AttachmentStore`` hold the documents.
Proves the Cowork round-trip — an agent reads an EXISTING document staged into
the sandbox, modifies it, and the change lands as a NEW version of the same
artifact (while documents it only read are not spuriously re-versioned).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from probos.artifacts import ArtifactStore
from probos.config import ExecutionConfig
from probos.tools.code_execution_tool import CodeExecutionTool


class _FakeAttachmentStore:
    """Protocol-faithful in-memory AttachmentStore with read (AD-1074d staging
    reads the prior version's bytes back out)."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str, str]] = {}

    async def write(self, content_hash, blob, mime, *, origin="chat_attachment"):
        self.blobs[content_hash] = (blob, mime, origin)
        return Path(f"/fake/{content_hash}")

    async def read(self, content_hash) -> bytes:
        if content_hash not in self.blobs:
            raise FileNotFoundError(content_hash)
        return self.blobs[content_hash][0]


def _runtime(tmp_path: Path, *, stage: bool = True, cap: int = 20):
    return SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True,
                scratch_dir=str(tmp_path / "scratch"),
                stage_thread_artifacts=stage,
                max_staged_artifacts=cap,
            ),
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"),
        attachment_store=_FakeAttachmentStore(),
    )


def _ctx(thread_id="thread-1", agent_id="ezri"):
    return {"thread_id": thread_id, "agent_id": agent_id}


async def _seed_doc(runtime, *, name: str, body: bytes, thread_id="thread-1"):
    """Persist v1 of a document the way ``_capture_artifacts`` would have."""
    content_hash = hashlib.sha256(body).hexdigest()
    await runtime.attachment_store.write(
        content_hash, body, "text/plain", origin="agent_artifact",
    )
    return runtime.artifact_store.add_version(
        thread_id=thread_id, name=name, content_hash=content_hash,
        mime="text/plain", size_bytes=len(body), created_by="ezri",
    )


async def test_agent_reads_and_modifies_an_existing_document(tmp_path) -> None:
    runtime = _runtime(tmp_path, stage=True)
    await _seed_doc(runtime, name="report.txt", body=b"heading: plain\n")
    tool = CodeExecutionTool(runtime=runtime)

    # The staged document is present in the cwd; the agent edits it in place.
    code = (
        "data = open('report.txt', encoding='utf-8').read()\n"
        "open('report.txt', 'w', encoding='utf-8').write(data.replace('plain', 'BOLD'))\n"
        "print('edited')\n"
    )
    result = await tool.invoke({"code": code}, _ctx())

    assert result.error is None
    assert "edited" in result.output["stdout"]
    # The edit re-captured report.txt as a NEW version of the SAME artifact.
    assert result.output["artifacts"] == ["report.txt"]
    versions = runtime.artifact_store.list_versions(thread_id="thread-1", name="report.txt")
    assert [v.version for v in versions] == [1, 2]
    assert versions[1].supersedes == versions[0].id
    # v2's bytes reflect the modification.
    blob, _mime, _origin = runtime.attachment_store.blobs[versions[1].content_hash]
    assert b"BOLD" in blob


async def test_untouched_staged_document_is_not_re_versioned(tmp_path) -> None:
    runtime = _runtime(tmp_path, stage=True)
    await _seed_doc(runtime, name="report.txt", body=b"keep me as-is\n")
    tool = CodeExecutionTool(runtime=runtime)

    # The agent produces a NEW file and never modifies the staged report.txt.
    code = (
        "open('summary.txt', 'w', encoding='utf-8').write('a fresh summary')\n"
        "print('done')\n"
    )
    result = await tool.invoke({"code": code}, _ctx())

    assert result.error is None
    # Only the new file is captured; the read-only document is not re-versioned.
    assert result.output["artifacts"] == ["summary.txt"]
    assert [
        v.version
        for v in runtime.artifact_store.list_versions(thread_id="thread-1", name="report.txt")
    ] == [1]


async def test_staging_disabled_leaves_workdir_empty(tmp_path) -> None:
    runtime = _runtime(tmp_path, stage=False)  # AD-1074d default OFF
    await _seed_doc(runtime, name="report.txt", body=b"not staged\n")
    tool = CodeExecutionTool(runtime=runtime)

    code = (
        "import os\n"
        "print('present' if os.path.exists('report.txt') else 'absent')\n"
    )
    result = await tool.invoke({"code": code}, _ctx())

    assert result.error is None
    assert "absent" in result.output["stdout"]


async def test_cap_zero_stages_nothing(tmp_path) -> None:
    runtime = _runtime(tmp_path, stage=True, cap=0)
    await _seed_doc(runtime, name="report.txt", body=b"capped out\n")
    tool = CodeExecutionTool(runtime=runtime)

    code = (
        "import os\n"
        "print('present' if os.path.exists('report.txt') else 'absent')\n"
    )
    result = await tool.invoke({"code": code}, _ctx())

    assert result.error is None
    assert "absent" in result.output["stdout"]
