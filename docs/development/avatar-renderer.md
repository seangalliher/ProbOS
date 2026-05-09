# AD-721i — Headless Avatar Renderer (Blender + saturday06 VRM-Addon)

> **Status:** v1 (Wave 134). Operator-installed prerequisites; ProbOS ships
> zero 3D assets.

ProbOS's agent-authored avatar pipeline (AD-721d) emits an `AvatarDSL`
artifact per agent — a structured, validated description of how the agent
wants to appear. This document describes how to install the headless
backend that turns that DSL into a `.vrm` file the HXI's `CrewVRM` viewer
already knows how to display.

## License posture

- **Apache 2.0 stays Apache 2.0.** The renderer module
  (`src/probos/avatars/blender_renderer.py`) NEVER imports `bpy` at module
  scope. `bpy` exists only inside the Blender subprocess Python that
  `asyncio.create_subprocess_exec` spawns.
- **Blender — GPL-3.0.** Subprocess-only boundary. **Bring Your Own
  Blender** — install separately. The repo never embeds `bpy`.
- **saturday06/VRM-Addon-for-Blender — MIT.** Operator-installed, not
  vendored.
- **No 3D assets ship.** Operator supplies meshes; or capsule fallback
  (E10) renders without any.

## Prerequisites

- **Blender ≥ 4.0** — VRM 1.0 export requires the modern saturday06
  add-on, which targets Blender 4.x.
- **saturday06 VRM-Addon-for-Blender ≥ 2.20** — the 2.x line is the
  Blender-4.x-compatible release stream (MIT-licensed; see the upstream
  `LICENSE` file).

### Windows install

```powershell
winget install BlenderFoundation.Blender
# Then download VRM-Addon-for-Blender release zip from
# https://github.com/saturday06/VRM-Addon-for-Blender/releases
# and install via Blender → Edit → Preferences → Add-ons → Install...
```

### Linux install

```bash
# Distribution package may lag — direct download is recommended.
wget https://download.blender.org/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz
tar -xf blender-4.0.2-linux-x64.tar.xz
sudo mv blender-4.0.2-linux-x64 /opt/blender
echo 'export PATH=/opt/blender:$PATH' >> ~/.bashrc

# VRM-Addon-for-Blender: same install flow as Windows — open Blender,
# Preferences → Add-ons → Install... → select the saturday06 zip.
```

After install, **enable the add-on** in Blender (Preferences → Add-ons →
search for "VRM" → check the box) and **save startup file**.

## Configuration

All renderer settings live on `cfg.avatars` (see
`src/probos/config.py:AvatarsConfig`).

| Field | Default | What it does |
|---|---|---|
| `enabled` | `True` | AD-721 master flag. When False, the avatar feature is off entirely. |
| `renderer_enabled` | `False` | AD-721i transitional flag. When False, the `regenerate_avatar` intent short-circuits without spawning Blender. Flip to True after operator confirms install end-to-end. |
| `blender_path` | `""` | Explicit binary path. Empty means "search PATH via `shutil.which('blender')`". |
| `blender_render_timeout_s` | `180` | Subprocess timeout. On timeout the renderer terminates Blender and raises `BlenderRenderError`. |
| `dsl_drafts_dir` | `"data/avatars/.drafts"` | Where DSL YAML / JSON drafts and per-render output VRMs land before the atomic move into `<avatars_dir>/<agent_id>.vrm`. |
| `procedural_base_mesh_fallback` | `True` | Captain ruling 2026-05-09. When True and no operator-supplied base mesh exists, the in-Blender script (E10) builds a minimal procedural humanoid capsule so v1 is end-to-end without operator base meshes. |
| `max_vrm_size_bytes` | `25 * 1024 * 1024` | Size cap for produced VRMs; oversized output is rejected and the partial file removed. |
| `avatars_dir` | `"data/avatars"` | Where rendered VRMs live (path-traversal-safe via `_resolve_avatars_dir`). |
| `fallback_to_parametric_on_error` | `True` | AD-721 setting. When the renderer is missing or fails, the HXI falls back to the parametric capsule. |

## Base mesh sourcing

The renderer expects an optional operator-supplied `.blend` at
`<avatars_dir>/_base_meshes/<body_type>.blend` where `<body_type>` is one
of `slim`, `average`, `stocky`. **The OSS repo ships zero base meshes.**
Any base mesh you drop in-tree is your licensing responsibility — the
repo does not audit nor distribute these files. License-audited starter
asset packs are deferred to **AD-721i-1**.

When no base mesh is present and `procedural_base_mesh_fallback=True`,
the in-Blender script (`_blender/render_avatar.py`) builds a minimal
capsule (cylinder body + UV-sphere head + single-bone armature) and
exports it. This is **intentionally crude** — it is the v1 smoke-test
path, not a production avatar.

## Troubleshooting

### "Blender not in PATH" / `BlenderNotFoundError`

Set `cfg.avatars.blender_path` to the explicit binary path, e.g.
`C:/Program Files/Blender Foundation/Blender 4.0/blender.exe`.

### "Add-on not enabled"

Open Blender → Edit → Preferences → Add-ons → search "VRM" → check the
box → File → Defaults → Save Startup File. The headless `--background`
process loads the saved startup, so a one-time interactive enable is
required.

### "Render timeout"

Raise `cfg.avatars.blender_render_timeout_s`. Default 180s is sized for
the procedural capsule path; complex operator-supplied meshes may need
longer. The renderer always terminates the subprocess on timeout
(`proc.terminate()` then `proc.wait(timeout=5)` then `proc.kill()`).

### "Output rejected — oversized / bad magic"

The produced file is not a valid VRM/glTF binary. Likely causes:

1. The saturday06 VRM-Addon is not enabled — Blender fell back to a
   non-VRM glTF export. Re-check the add-on enable step above.
2. Output exceeds `max_vrm_size_bytes` (default 25 MB). Either simplify
   the base mesh or raise the cap (note: HXI loader honours the same cap).

In both cases the renderer logs the failure with what/why/what-next
context (per Engineering Principles), removes the partial file, and
raises a typed `BlenderRenderError`. AD-721d's DSL persists either way —
the agent's design is never lost.

## Forward markers

- **AD-721i-1** — license-audited starter asset pack (CC0/Apache base
  meshes, hair, outfits). Per-asset license audit is its own AD.
- **AD-721i-2** — VRoid Studio CLI alternative backend evaluation.
- **AD-721j** — Computer Use Blender control (outside-DSL artistry,
  already filed in the AD-721 ladder).
