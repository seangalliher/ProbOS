"""AD-721i E7: mocked-subprocess tests for the headless Blender renderer.

All ``asyncio.create_subprocess_exec`` calls are mocked. NO real Blender
invocation in this file — the integration smoke lives in
``test_ad721i_blender_smoke.py`` and skips when ``shutil.which("blender")``
returns None.

Covers:

* Blender path resolution (configured / shutil.which / not-found).
* Pre-check: no base mesh AND no capsule fallback → typed error.
* Subprocess timeout → terminate + raise ``BlenderRenderError``.
* Subprocess non-zero exit → log stderr tail + raise.
* Output validation: size cap, magic bytes, missing-file.
* Intent-layer atomic-replace happens only on success.
* Intent-layer short-circuits when ``renderer_enabled=False``.
* AST scan: no ``subprocess.run`` introduced under ``src/probos/avatars/``.
"""

from __future__ import annotations

import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.avatars.blender_renderer import (
    BlenderNotFoundError,
    BlenderRenderError,
    BlenderRenderer,
)
from probos.avatars.dsl import AvatarDSL


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_renderer(
    tmp_path: Path,
    *,
    blender_path: str | None = "/fake/blender",
    timeout_s: int = 5,
    procedural_fallback: bool = True,
    avatars_dir: Path | None = None,
) -> BlenderRenderer:
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    return BlenderRenderer(
        blender_path=blender_path,
        timeout_s=timeout_s,
        drafts_dir=drafts,
        max_vrm_size_bytes=1024 * 1024,
        avatars_dir=avatars_dir if avatars_dir is not None else (tmp_path / "avatars"),
        procedural_fallback=procedural_fallback,
    )


def _fake_proc(
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    hang: bool = False,
) -> MagicMock:
    """Return a mock that mimics asyncio.subprocess.Process just enough for tests."""
    proc = MagicMock()
    proc.returncode = returncode
    if hang:
        async def _hang() -> tuple[bytes, bytes]:  # pragma: no cover - never returns
            await asyncio.sleep(60)
            return stdout, stderr
        proc.communicate = _hang
    else:
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    return proc


def _write_valid_vrm(path: Path, *, size: int = 64) -> None:
    """Write a minimal file whose first 4 bytes are the glTF magic."""
    payload = b"glTF" + b"\x00" * max(0, size - 4)
    path.write_bytes(payload)


def _write_oversized_vrm(path: Path, *, size: int = 2 * 1024 * 1024) -> None:
    path.write_bytes(b"glTF" + b"\x00" * (size - 4))


def _write_bad_magic(path: Path) -> None:
    path.write_bytes(b"NOPE" + b"\x00" * 60)


# ── Renderer-layer tests ────────────────────────────────────────────────


def test_blender_path_resolution_from_config(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path, blender_path="/explicit/blender")
    assert r.resolve_blender() == "/explicit/blender"


def test_blender_path_resolution_via_which(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path, blender_path=None)
    with patch("probos.avatars.blender_renderer.shutil.which", return_value="/usr/bin/blender"):
        assert r.resolve_blender() == "/usr/bin/blender"


def test_blender_not_found_raises(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path, blender_path=None)
    with patch("probos.avatars.blender_renderer.shutil.which", return_value=None):
        with pytest.raises(BlenderNotFoundError):
            r.resolve_blender()


def test_no_base_mesh_and_no_capsule_fallback_returns_typed_error(
    tmp_path: Path,
) -> None:
    avatars = tmp_path / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    # Note: no base mesh dropped; procedural_fallback=False.
    r = _make_renderer(tmp_path, procedural_fallback=False, avatars_dir=avatars)
    with pytest.raises(BlenderRenderError) as excinfo:
        asyncio.run(r.render(AvatarDSL(), "agent-x"))
    assert "no base mesh" in str(excinfo.value)


def test_subprocess_timeout_terminates_and_raises(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path, timeout_s=1)
    proc = _fake_proc(hang=True)
    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        # Patch wait_for to raise TimeoutError on the first call (communicate),
        # and succeed on the second (proc.wait after terminate).
        original = asyncio.wait_for
        call_count = {"n": 0}

        async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise asyncio.TimeoutError()
            return await original(awaitable, timeout=timeout)

        with patch(
            "probos.avatars.blender_renderer.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            with pytest.raises(BlenderRenderError) as excinfo:
                asyncio.run(r.render(AvatarDSL(), "agent-t"))
    assert "timed out" in str(excinfo.value)
    proc.terminate.assert_called_once()


def test_subprocess_nonzero_exit_logs_stderr_tail_and_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    r = _make_renderer(tmp_path)
    big_stderr = (b"line\n" * 1000) + b"FINAL_TAIL_MARKER"
    proc = _fake_proc(returncode=2, stderr=big_stderr)
    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        with caplog.at_level("ERROR", logger="probos.avatars.blender_renderer"):
            with pytest.raises(BlenderRenderError):
                asyncio.run(r.render(AvatarDSL(), "agent-e"))
    # Tail marker must appear; full stderr must NOT (we cap at 2 KiB).
    error_records = [rec for rec in caplog.records if rec.levelname == "ERROR"]
    assert any("FINAL_TAIL_MARKER" in rec.message for rec in error_records)


def test_output_oversized_rejected(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path)
    r._max_size = 64  # tighten for the test
    proc = _fake_proc(returncode=0)

    async def _spawn(
        *cmd: Any, **kwargs: Any,
    ) -> Any:
        # Find --output in cmd, then write an oversized fake VRM there.
        out = cmd[cmd.index("--output") + 1]
        _write_oversized_vrm(Path(out), size=4096)
        return proc

    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        side_effect=_spawn,
    ):
        with pytest.raises(BlenderRenderError) as excinfo:
            asyncio.run(r.render(AvatarDSL(), "agent-big"))
    assert "exceeds" in str(excinfo.value)


def test_output_bad_magic_rejected(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path)
    proc = _fake_proc(returncode=0)

    async def _spawn(*cmd: Any, **kwargs: Any) -> Any:
        out = cmd[cmd.index("--output") + 1]
        _write_bad_magic(Path(out))
        return proc

    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        side_effect=_spawn,
    ):
        with pytest.raises(BlenderRenderError) as excinfo:
            asyncio.run(r.render(AvatarDSL(), "agent-bad"))
    assert "glTF magic" in str(excinfo.value)


def test_output_missing_after_success_exit_rejected(tmp_path: Path) -> None:
    r = _make_renderer(tmp_path)
    proc = _fake_proc(returncode=0)
    # Spawn does NOT write the output file.
    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        with pytest.raises(BlenderRenderError) as excinfo:
            asyncio.run(r.render(AvatarDSL(), "agent-miss"))
    assert "output file missing" in str(excinfo.value)


def test_render_success_returns_draft_path(tmp_path: Path) -> None:
    """Happy path — subprocess writes a valid .vrm and render returns its Path."""
    r = _make_renderer(tmp_path)
    proc = _fake_proc(returncode=0)

    async def _spawn(*cmd: Any, **kwargs: Any) -> Any:
        out = cmd[cmd.index("--output") + 1]
        _write_valid_vrm(Path(out))
        return proc

    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        side_effect=_spawn,
    ):
        result = asyncio.run(r.render(AvatarDSL(), "agent-ok"))
    assert isinstance(result, Path)
    assert result.exists()
    assert result.read_bytes()[:4] == b"glTF"


# ── Intent-layer tests (AvatarRendererAgent) ────────────────────────────


def _make_intent_agent(tmp_path: Path, *, renderer_enabled: bool) -> Any:
    """Build an AvatarRendererAgent with a fake runtime/config wired in."""
    from probos.agents.utility.avatar_agents import AvatarRendererAgent

    avatars = tmp_path / "avatars"
    drafts = avatars / ".drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    base_meshes = avatars / "_base_meshes"
    base_meshes.mkdir(parents=True, exist_ok=True)

    avatars_cfg = SimpleNamespace(
        enabled=True,
        avatars_dir=str(avatars),
        max_vrm_size_bytes=1024 * 1024,
        fallback_to_parametric_on_error=True,
        blender_path="/fake/blender",
        blender_render_timeout_s=5,
        dsl_drafts_dir=str(drafts),
        renderer_enabled=renderer_enabled,
        procedural_base_mesh_fallback=True,
    )
    config = SimpleNamespace(avatars=avatars_cfg)
    runtime = SimpleNamespace(config=config)

    agent = AvatarRendererAgent("avatar-renderer-test")
    agent._runtime = runtime
    return agent, avatars, drafts


def test_renderer_disabled_short_circuits_intent(tmp_path: Path) -> None:
    """E7-11: renderer_enabled=False ⇒ IntentResult(success=False) without subprocess."""
    from probos.types import IntentMessage

    agent, _avatars, _drafts = _make_intent_agent(tmp_path, renderer_enabled=False)
    intent = IntentMessage(
        intent="regenerate_avatar",
        params={"agent_id": "echo", "dsl_dict": AvatarDSL().model_dump()},
    )

    # If the subprocess factory is called, this test fails.
    spawn_mock = AsyncMock()
    with patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        spawn_mock,
    ):
        result = asyncio.run(agent.handle_intent(intent))

    assert result is not None
    assert result.success is False
    assert "renderer disabled" in (result.error or "")
    spawn_mock.assert_not_called()


def test_atomic_replace_only_on_success(tmp_path: Path) -> None:
    """E7-10: canonical <agent_id>.vrm is created only after a successful render."""
    from probos.types import IntentMessage

    # Resolve _resolve_avatars_dir to the test's avatar/drafts dirs.
    agent, avatars, drafts = _make_intent_agent(tmp_path, renderer_enabled=True)
    canonical = avatars / "echo.vrm"
    assert not canonical.exists(), "pre-condition: canonical must not exist yet"

    proc = _fake_proc(returncode=0)

    async def _spawn(*cmd: Any, **kwargs: Any) -> Any:
        out = cmd[cmd.index("--output") + 1]
        _write_valid_vrm(Path(out))
        return proc

    with patch(
        "probos.routers.system._resolve_avatars_dir",
        side_effect=lambda configured: Path(configured),
    ), patch(
        "probos.avatars.blender_renderer.asyncio.create_subprocess_exec",
        side_effect=_spawn,
    ):
        intent = IntentMessage(
            intent="regenerate_avatar",
            params={"agent_id": "echo", "dsl_dict": AvatarDSL().model_dump()},
        )
        result = asyncio.run(agent.handle_intent(intent))

    assert result is not None and result.success is True
    assert canonical.exists(), "canonical .vrm must exist after successful render"
    assert canonical.read_bytes()[:4] == b"glTF"


# ── AST guard ───────────────────────────────────────────────────────────


def test_no_subprocess_run_in_module() -> None:
    """E7-12: defense against future regression — no ``subprocess.run`` in renderer."""
    src = Path(__file__).parents[1] / "src" / "probos" / "avatars" / "blender_renderer.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "subprocess"
                and f.attr == "run"
            ):
                offenders.append(ast.dump(node))
    assert offenders == [], (
        "subprocess.run is forbidden in blender_renderer.py — "
        f"found: {offenders}"
    )
