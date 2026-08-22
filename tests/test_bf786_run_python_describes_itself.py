"""BF-786 (#1250): two run_python claims that did not match the code.

Both are the shape BF-726 exists to prevent -- the sandbox misdescribing its
own limits -- and both fail silently, because the model plans against the
description and only the outcome disagrees.

1. The output cap was rendered as a total. `isolation.py` slices it onto
   stdout and stderr SEPARATELY, so a run can return twice the advertised
   figure. Measured on the issue: `max_output_bytes=1024` returned 1024 bytes
   of stdout AND 1024 of stderr.

2. "Any file the script writes ... is saved" was false. `_capture_artifacts`
   skips empty files, files over 25 MiB, machinery paths, the sandbox's own
   script, and staged inputs the script did not modify. The agent believes it
   produced an artifact the Captain never sees -- the BF-720 shape, where the
   agent's belief and the delivered result diverge with nothing reporting it.

Each claim is pinned against the CODE it describes, not against the wording,
so drift on either side fails rather than passing quietly.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.tools.code_execution_tool import (
    _MAX_ARTIFACT_BYTES,
    CodeExecutionTool,
)


def _tool(**cfg_kw):
    defaults = {
        "timeout_seconds": 30,
        "max_output_bytes": 65536,
        "max_memory_mb": 512,
        "fetch_broker_enabled": False,
    }
    defaults.update(cfg_kw)
    cfg = SimpleNamespace(**defaults)
    tool = CodeExecutionTool.__new__(CodeExecutionTool)
    tool._cfg = lambda: cfg  # type: ignore[method-assign]
    return tool


# ── 1. the output cap is per stream ───────────────────────────────


def test_the_output_cap_is_described_as_per_stream() -> None:
    description = _tool(max_output_bytes=65536).description

    assert "64 KB of captured output per stream" in description
    assert "stdout and stderr each" in description


def test_the_cap_really_is_applied_per_stream() -> None:
    """The premise of the wording above, held STRUCTURALLY.

    This is a source scan, and says so: it counts the two independent slices of
    the same cap that make "per stream" true. A source scan cannot tell a
    requirement from a mention of one, so it is deliberately narrow -- it fails
    if the two slices become one shared budget, which is the drift that would
    make the description wrong again.

    Review confirmed the behaviour separately against a real sandbox run: a
    1,024-byte cap returned 1,024 bytes of stdout AND 1,024 of stderr. That
    execution needs a sandbox this unit test does not have.
    """
    from probos.execution import isolation

    src = inspect.getsource(isolation)
    assert src.count("[:cap]") == 2, src.count("[:cap]")


# ── 2. the artifact rule ──────────────────────────────────────────


def test_the_description_does_not_promise_that_any_file_is_saved() -> None:
    description = _tool().description

    assert "Any file the" not in description
    assert "Empty files" in description
    assert "25 MiB" in description
    assert "staged inputs the script did not modify" in description


@pytest.mark.asyncio
async def test_an_empty_file_is_not_captured(tmp_path: Path) -> None:
    """The exclusion the description now names, exercised."""
    captured = await _capture(tmp_path, {"empty.txt": b"", "real.txt": b"data"})
    assert captured == ["real.txt"], captured


@pytest.mark.asyncio
async def test_an_unmodified_staged_input_is_not_recaptured(tmp_path: Path) -> None:
    import hashlib

    blob = b"unchanged"
    staged = {"input.txt": hashlib.sha256(blob).hexdigest()}
    captured = await _capture(
        tmp_path, {"input.txt": blob, "new.txt": b"fresh"}, staged=staged,
    )
    assert captured == ["new.txt"], captured


def test_the_size_ceiling_the_description_names_is_the_one_enforced() -> None:
    """MiB, not MB. Review measured a 25,500,000-byte file -- over 25 MB and
    under 25 MiB -- being captured, so the first wording was a new false claim
    in place of the old one."""
    assert _MAX_ARTIFACT_BYTES == 25 * 1024 * 1024
    assert f"{_MAX_ARTIFACT_BYTES // (1024 * 1024)} MiB" == "25 MiB"
    assert "25 MiB" in _tool().description


@pytest.mark.asyncio
async def test_the_ceiling_bites_at_the_byte_it_names(tmp_path: Path) -> None:
    """At the cap and one over it, so the boundary is pinned rather than the
    order of magnitude."""
    captured = await _capture(
        tmp_path,
        {
            "at_cap.bin": b"x" * _MAX_ARTIFACT_BYTES,
            "over_cap.bin": b"x" * (_MAX_ARTIFACT_BYTES + 1),
        },
    )
    assert captured == ["at_cap.bin"], captured


# ── harness ───────────────────────────────────────────────────────


async def _capture(
    workdir: Path, files: dict[str, bytes], staged: dict[str, str] | None = None,
) -> list[str]:
    for name, blob in files.items():
        (workdir / name).write_bytes(blob)

    saved: list[str] = []

    async def _write(content_hash, blob, mime, **kwargs):
        return SimpleNamespace(id="a", content_hash=content_hash)

    def _add_version(*, name, content_hash, size_bytes, **kwargs):
        saved.append(name)
        return SimpleNamespace(
            id="art", content_hash=content_hash, thread_id="t", name=name,
            mime="text/plain", size_bytes=size_bytes, version=1,
            created_at=0.0, created_by="c",
        )

    tool = _tool()
    tool._runtime = SimpleNamespace(  # type: ignore[attr-defined]
        attachment_store=SimpleNamespace(write=_write),
        artifact_store=SimpleNamespace(add_version=_add_version),
    )
    await tool._capture_artifacts(
        workdir, thread_id="t", created_by="c", staged=staged,
    )
    return sorted(saved)
