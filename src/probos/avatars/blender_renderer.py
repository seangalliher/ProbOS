"""AD-721i: headless Blender renderer for AvatarDSL → VRM.

Async-only. Blender is a GPL-3.0 program — we treat it as an OS-level
subprocess (BYOL). Apache 2.0 boundary preserved: this module never
imports ``bpy`` at top level. ``bpy`` exists only inside the Blender
subprocess Python that ``asyncio.create_subprocess_exec`` spawns.

Forbidden in this module:
  * ``subprocess.run`` (any sync subprocess invocation)
  * ``exec`` / ``eval`` / ``compile`` on DSL content
  * ``import bpy`` at module / function scope
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from probos.avatars.dsl import AvatarDSL

logger = logging.getLogger(__name__)


# ── Errors ──────────────────────────────────────────────────────────────


class BlenderNotFoundError(RuntimeError):
    """Raised when no Blender binary can be resolved (operator BYOL not installed).

    Carries the searched paths so the typed error tells the agent what to fix.
    """

    def __init__(self, *, configured: str, message: str = "") -> None:
        self.configured = configured
        super().__init__(
            message
            or f"Blender binary not found (configured={configured!r}, "
            "searched PATH via shutil.which('blender'))",
        )


class BlenderRenderError(RuntimeError):
    """Raised on any non-success outcome from the renderer subprocess.

    Subclasses are not used — the typed string carries the failure reason
    so callers can branch (timeout vs nonzero exit vs bad output) without
    parsing the message. The intent layer (``avatar_agents.py``) converts
    this into a non-success ``IntentResult`` so the agent's design is not lost.
    """


# ── Renderer ────────────────────────────────────────────────────────────


# AD-721i E3: bundled render script path (executed only inside Blender's
# subprocess Python — see _blender/render_avatar.py).
_RENDER_SCRIPT_PATH = (Path(__file__).parent / "_blender" / "render_avatar.py").resolve()


class BlenderRenderer:
    """Async wrapper around ``blender --background --python <render_script>``.

    Construction performs no I/O beyond ``shutil.which``. Subprocess is invoked
    only inside ``render``.
    """

    def __init__(
        self,
        blender_path: str | None,
        timeout_s: int,
        drafts_dir: Path,
        max_vrm_size_bytes: int,
        avatars_dir: Path | None = None,
        procedural_fallback: bool = True,
    ) -> None:
        self._configured = blender_path or ""
        self._timeout_s = int(timeout_s)
        self._drafts_dir = Path(drafts_dir)
        self._max_size = int(max_vrm_size_bytes)
        self._avatars_dir = Path(avatars_dir) if avatars_dir else None
        self._procedural_fallback = bool(procedural_fallback)
        # Lazy resolution: do not raise at construction time so a runtime
        # without Blender can still construct the agent and short-circuit.
        self._resolved_blender: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_blender(self) -> str:
        """Resolve the Blender binary path. Raises ``BlenderNotFoundError``
        when neither the configured value nor ``shutil.which`` resolves.
        """
        if self._resolved_blender:
            return self._resolved_blender
        if self._configured:
            self._resolved_blender = self._configured
            return self._resolved_blender
        which = shutil.which("blender")
        if which:
            self._resolved_blender = which
            return which
        raise BlenderNotFoundError(configured=self._configured)

    async def render(self, dsl: "AvatarDSL", agent_id: str) -> Path:
        """Run Blender headless, produce a ``.vrm``. Return the output Path.

        Raises:
            BlenderNotFoundError: Blender binary cannot be resolved.
            BlenderRenderError: subprocess timed out, exited non-zero, or
                produced an output file that fails validation (size cap,
                magic-bytes check, missing file).
        """
        # Defense-in-depth: re-validate the DSL at the renderer entry, even
        # though the intent layer also validated it.
        from probos.avatars.dsl import AvatarDSL  # local import keeps startup graph small

        if not isinstance(dsl, AvatarDSL):
            raise BlenderRenderError(
                f"render: expected AvatarDSL instance, got {type(dsl).__name__}"
            )

        # Pre-check: before consuming a subprocess slot, verify the renderer
        # can resolve a base mesh path (or has procedural fallback enabled).
        if not self._procedural_fallback and self._avatars_dir is not None:
            base_mesh = self._avatars_dir / "_base_meshes" / f"{dsl.body.type}.blend"
            if not base_mesh.exists():
                msg = (
                    f"no base mesh installed for body.type={dsl.body.type!r}; "
                    f"DSL preserved at <drafts_dir>/{agent_id}.dsl.json"
                )
                logger.warning(
                    "AD-721i: pre-check failed (%s); refusing to spawn Blender",
                    msg,
                )
                raise BlenderRenderError(msg)

        blender = self.resolve_blender()

        # Persist DSL to a temp YAML for the in-Blender script to read.
        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        yaml_path = self._drafts_dir / f"{agent_id}_{ts}.dsl.yaml"
        output_path = self._drafts_dir / f"{agent_id}_{ts}.vrm"
        # Also persist a stable drafts JSON copy so a renderer failure leaves
        # the design discoverable on disk (matches the typed-error contract).
        json_path = self._drafts_dir / f"{agent_id}.dsl.json"
        try:
            yaml_path.write_text(yaml.safe_dump(dsl.model_dump()), encoding="utf-8")
            import json as _json
            json_path.write_text(_json.dumps(dsl.model_dump(), indent=2), encoding="utf-8")
        except OSError as exc:
            raise BlenderRenderError(
                f"failed to persist DSL to drafts dir {self._drafts_dir}: {exc}"
            ) from exc

        cmd = [
            blender,
            "--background",
            "--factory-startup",
            "--python", str(_RENDER_SCRIPT_PATH),
            "--",
            "--dsl", str(yaml_path),
            "--output", str(output_path),
            "--procedural-fallback", "1" if self._procedural_fallback else "0",
        ]
        if self._avatars_dir is not None:
            cmd.extend(["--avatars-dir", str(self._avatars_dir)])

        logger.info(
            "AD-721i: invoking Blender renderer for agent=%s timeout=%ds",
            agent_id, self._timeout_s,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, FileNotFoundError) as exc:
            raise BlenderRenderError(f"failed to spawn Blender subprocess: {exc}") from exc

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AD-721i: Blender render TIMED OUT after %ds for agent=%s; "
                "terminating subprocess; DSL preserved at %s",
                self._timeout_s, agent_id, json_path,
            )
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            raise BlenderRenderError(
                f"render timed out after {self._timeout_s}s for agent={agent_id}"
            )

        if proc.returncode != 0:
            tail_bytes = (stderr_b or b"")[-2048:]
            tail = tail_bytes.decode("utf-8", errors="replace")
            logger.error(
                "AD-721i: Blender exited non-zero (%d) for agent=%s; "
                "DSL preserved at %s; stderr tail (last 2 KiB):\n%s",
                proc.returncode, agent_id, json_path, tail,
            )
            # Best-effort cleanup of any partial output.
            try:
                if output_path.exists():
                    output_path.unlink()
            except OSError:
                pass
            raise BlenderRenderError(
                f"Blender exited {proc.returncode} for agent={agent_id}; "
                f"see logs for stderr tail"
            )

        # Validate the produced .vrm.
        if not output_path.exists() or not output_path.is_file():
            raise BlenderRenderError(
                f"Blender exited 0 but output file missing at {output_path}",
            )
        try:
            size = output_path.stat().st_size
        except OSError as exc:
            raise BlenderRenderError(
                f"failed to stat output {output_path}: {exc}"
            ) from exc
        if size > self._max_size:
            try:
                output_path.unlink()
            except OSError:
                pass
            raise BlenderRenderError(
                f"output {output_path} ({size} bytes) exceeds "
                f"max_vrm_size_bytes={self._max_size}"
            )

        # First 4 bytes must be the glTF magic — VRM 1.0 is a glTF binary container.
        try:
            with output_path.open("rb") as fh:
                magic = fh.read(4)
        except OSError as exc:
            raise BlenderRenderError(
                f"failed to read output {output_path}: {exc}"
            ) from exc
        if magic != b"glTF":
            try:
                output_path.unlink()
            except OSError:
                pass
            raise BlenderRenderError(
                f"output {output_path} does not have glTF magic bytes "
                f"(got {magic!r}); not a valid VRM"
            )

        logger.info(
            "AD-721i: Blender render succeeded for agent=%s output=%s size=%d bytes",
            agent_id, output_path, size,
        )
        return output_path


__all__ = [
    "BlenderNotFoundError",
    "BlenderRenderError",
    "BlenderRenderer",
]
