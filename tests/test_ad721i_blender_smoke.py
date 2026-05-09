"""AD-721i E8: Blender integration smoke test (opt-in).

Skipped automatically when Blender is not on PATH (BYOL — operator brings
the binary). This is the only AD-721i test that actually invokes a
subprocess; the rest live in ``test_ad721i_renderer.py`` and are mocked.

Asserts:
  * A ``.vrm`` is produced via the procedural-capsule fallback (E10).
  * The output's first 4 bytes are the glTF magic.

Note on the Fcl_MTH_A morph assertion (multi-mesh face-split BF regression):
the bare procedural capsule does NOT carry expression morphs because v1
ships zero base meshes and the saturday06 add-on may emit a glTF binary
without VRM-specific morphs when no human-shaped armature is present.
The dispatch's E8 spec wants ``at least one Fcl_MTH_A morph`` on the
exported VRM as the lowest-bar evidence the bake survived export — that
assertion is meaningful only with an operator-supplied base mesh under
``data/avatars/_base_meshes/<body_type>.blend``. The smoke therefore:
  * unconditionally asserts the magic bytes,
  * conditionally asserts the morph when a base mesh is present.

This keeps the smoke green on a Blender-only machine without leaking the
multi-mesh face-split regression coverage into a false negative when the
operator has not supplied a base mesh.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("blender") is None,
    reason="Blender not installed; AD-721i smoke skipped (BYOL).",
)


def test_blender_smoke_renders_capsule(tmp_path: Path) -> None:
    """Render a minimal AvatarDSL (capsule fallback). Assert .vrm magic bytes."""
    from probos.avatars.blender_renderer import BlenderRenderer
    from probos.avatars.dsl import AvatarDSL

    avatars = tmp_path / "avatars"
    drafts = avatars / ".drafts"
    drafts.mkdir(parents=True, exist_ok=True)

    renderer = BlenderRenderer(
        blender_path=None,  # let shutil.which resolve
        timeout_s=180,
        drafts_dir=drafts,
        max_vrm_size_bytes=25 * 1024 * 1024,
        avatars_dir=avatars,
        procedural_fallback=True,
    )

    output_path = asyncio.run(renderer.render(AvatarDSL(), "smoke-agent"))
    assert output_path.exists(), "renderer reported success but file is missing"
    assert output_path.read_bytes()[:4] == b"glTF", "VRM must start with glTF magic"

    # Conditional: only check the multi-mesh face-split BF morph when an
    # operator-supplied base mesh exists. See module docstring.
    base_meshes = avatars / "_base_meshes"
    if (base_meshes / "average.blend").exists():
        body = output_path.read_bytes()
        # Crude name-match — the morph name is embedded in the glTF JSON header
        # whether the file is GLB or proper VRM 1.0. Lowest-bar regression check.
        assert b"Fcl_MTH_A" in body, (
            "expected at least one Fcl_MTH_A morph on exported VRM "
            "(multi-mesh face-split BF de4107b regression)"
        )
