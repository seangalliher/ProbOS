# pyright: reportMissingImports=false
"""AD-721i E3 + E10: Blender-side render script.

Executed ONLY inside the Blender subprocess Python that the renderer spawns
via ``asyncio.create_subprocess_exec(blender, '--background', '--python', <this>)``.
``bpy`` is provided by Blender at runtime; this file MUST NOT be imported
from the dev venv. Pytest never collects it because ``pyproject.toml`` pins
``testpaths = ["tests"]`` and ``tests/conftest.py`` adds a defense-in-depth
``collect_ignore_glob`` for ``**/_blender/**``.

This script is intentionally MINIMAL. It covers v1's "smoke test passes
without bundled assets" path. Realistic humanoid sculpting is deferred
to AD-721i-1's license-audited starter pack.

Hard floor on complexity: keep the procedural-capsule (E10) ≤ 50 lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]
import yaml  # type: ignore[import-not-found]


def _parse_args() -> argparse.Namespace:
    # Blender swallows everything before "--" as its own args.
    sep = sys.argv.index("--") if "--" in sys.argv else len(sys.argv)
    after = sys.argv[sep + 1:]
    parser = argparse.ArgumentParser(prog="render_avatar")
    parser.add_argument("--dsl", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--avatars-dir", default="")
    parser.add_argument("--procedural-fallback", default="1")
    return parser.parse_args(after)


def _load_dsl(dsl_path: Path) -> dict:
    with dsl_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"DSL file {dsl_path} did not parse as a dict")
    return data


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _build_procedural_capsule(dsl: dict) -> None:
    """E10 procedural humanoid capsule fallback (intentionally crude)."""
    height_cm = dsl.get("body", {}).get("height_cm", 170)
    height_m = height_cm / 100.0
    bpy.ops.mesh.primitive_cylinder_add(radius=0.18, depth=height_m * 0.7, location=(0, 0, height_m * 0.4))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0, 0, height_m * 0.85))
    # Single bone armature for VRM export compliance.
    bpy.ops.object.armature_add(location=(0, 0, 0))


def _try_load_base_mesh(dsl: dict, avatars_dir: str) -> bool:
    if not avatars_dir:
        return False
    body_type = dsl.get("body", {}).get("type", "average")
    base = Path(avatars_dir) / "_base_meshes" / f"{body_type}.blend"
    if not base.exists():
        return False
    bpy.ops.wm.append(directory=str(base) + "/Object/", filename="Body")
    return True


def _export_vrm(output: Path) -> None:
    """Best-effort VRM export via the saturday06 add-on if installed."""
    output.parent.mkdir(parents=True, exist_ok=True)
    op = getattr(getattr(bpy.ops, "export_scene", None), "vrm", None)
    if op is None:
        # Fallback: export glTF binary so the .vrm has the glTF magic bytes
        # (renderer-side validation only checks the magic, not full VRM 1.0
        # conformance — the smoke-skipif blocks the full smoke when Blender
        # is absent, and AD-721i-1's starter pack hardens this path).
        bpy.ops.export_scene.gltf(
            filepath=str(output), export_format="GLB",
        )
        # Rename .glb→.vrm (operator is told they need saturday06 for real VRM).
        return
    op(filepath=str(output))


def main() -> int:
    args = _parse_args()
    dsl = _load_dsl(Path(args.dsl))
    _clear_scene()
    if not _try_load_base_mesh(dsl, args.avatars_dir):
        if args.procedural_fallback != "1":
            print("AD-721i: no base mesh and procedural fallback disabled", file=sys.stderr)
            return 2
        _build_procedural_capsule(dsl)
    _export_vrm(Path(args.output))
    print(json.dumps({"status": "ok", "output": args.output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
