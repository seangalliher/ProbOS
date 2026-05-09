# AD-721i — DSL → Blender VRM renderer (headless backend, v1)

**Wave:** 134
**Depends on:** AD-721d (same wave; pair-built; merge order d → i)
**Issue:** [#537](https://github.com/seangalliher/ProbOS/issues/537)
**Risk:** MEDIUM-HIGH (subprocess + bundled in-Blender script + license boundary)
**Estimated tests:** ≥ 12 Python (mocked) + 1 Blender smoke (skipped without Blender)

> **Builder:** read `prompts/WAVE-134-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

Headless backend that consumes an `AvatarDSL` (from AD-721d) and produces a `.vrm` file under `<avatars_dir>/<agent_id>.vrm` via a Blender subprocess. v1 ships **zero third-party 3D assets** — operator either drops a base mesh under `data/avatars/_base_meshes/` or relies on the procedural humanoid capsule fallback (E10) for end-to-end smoke. When Blender is absent, the renderer **fails cleanly** (typed error, structured log) — AD-721d's DSL is preserved either way.

## 2. License posture

- **OSS Apache 2.0 stays Apache 2.0.** Confirmed.
- **Blender (GPL-3.0)** — invoked as an OS-level subprocess only. The Apache 2.0 repository never imports `bpy` as a Python library at module-level. `bpy.ops` runs only inside the Blender-spawned subprocess Python. Subprocess invocation is OS-level, not derivative work — preserves the Apache 2.0 boundary.
- **`saturday06/VRM-Addon-for-Blender`** — MIT licensed. Operator-installed (not vendored). Documented as a prerequisite alongside Blender.
- **No 3D assets ship.** Operator supplies meshes; or capsule fallback (E10) renders without any.
- **BYOL** — operator brings the `blender` binary. Default install path search: configured `blender_path` → `shutil.which("blender")` → `BlenderNotFoundError`.

**Targeted minimum versions** (drafter-confirmed prerequisites; document in E9):

- **Blender ≥ 4.0** (VRM 1.0 export requires the modern saturday06 add-on, which targets Blender 4.x).
- **saturday06 VRM-Addon-for-Blender ≥ 2.20** (the 2.x line is the Blender-4.x-compatible release stream; latest stable as of 2026-05-09 is in the 2.x range; MIT-licensed per the upstream repo's `LICENSE`).

If the Builder discovers at smoke-test time that a newer minimum is required, document it in E9 and update this section — do NOT silently raise the floor.

## 3. Verified Against Codebase (2026-05-09)

```
grep -n "create_subprocess_exec" src/probos
  src/probos/worktree_manager.py:52:   proc = await asyncio.create_subprocess_exec(...)
  src/probos/cognitive/builder.py:2534: proc = await asyncio.create_subprocess_exec(...)
  src/probos/cognitive/builder.py:2545: proc = await asyncio.create_subprocess_exec(...)

grep -n "intent_descriptors\s*=" src/probos/agents/utility/web_agents.py
  82, 125, 169, 221  — class-level lists on BaseAgent subclasses (real registrations)

grep -n "intent_descriptors\s*=" src/probos/agents/utility/language_agents.py
  32, 55  — same pattern

grep -n "IntentDescriptor(" src/probos/cognitive/agent_designer.py
  119, 155  — string-template literals emitted INTO LLM-generated agent code,
              NOT real registrations. Builder MUST NOT add a real registration here.

grep -n "class AvatarsConfig" src/probos/config.py
  922: enabled: bool = True
  926: avatars_dir: str = "data/avatars"
  927: max_vrm_size_bytes: int = 25 * 1024 * 1024
  928: fallback_to_parametric_on_error: bool = True

grep -n "_resolve_avatars_dir" src/probos/routers/system.py
  641 — BF #539 path-traversal-safe avatar dir resolver.

grep -n "testpaths\|addopts" pyproject.toml
  93: testpaths = ["tests"]      # constrains pytest collection.
  100: addopts = "-n 16 --dist=loadfile"
```

> **Note:** `WAVE-134-DISPATCH.md` §4 D4 cited a `profile_store.py` that does not exist; that's an AD-721d-side concern (the Architect's verify-first against AD-721d's prompt body resolved this — `ProfileStore` is in `crew_profile.py:287`). Mentioned here only because the dispatch reads as if `profile_store.py` is a real file and AD-721i must NOT touch profile persistence.

## 4. Scope (v1 only)

E1–E10 below. Renderer is async-subprocess-only. v1 ships zero 3D assets. Capsule fallback default-on so end-to-end works with zero operator setup.

## 5. Non-goals (deferred forward markers)

- **AD-721i-1** — license-audited starter asset pack (CC0/Apache base meshes, hair, outfits). Issue #537 D3 is too broad for v1; per-asset license audit is its own AD. File at gate-3.
- **AD-721i-2** — VRoid Studio CLI alternative backend. Issue #537 mentions it as a research note; v1 picks Blender + saturday06. File at gate-3 if Captain wants the option.
- **AD-721j** — Computer Use Blender control (outside-DSL artistry). Issue #537 explicitly defers this. Already filed.
- **Render preview UI in HXI** — deferred to AD-721d-1.

## 6. Deliverables

### E1 — `BlenderRenderer` async class

**New file:** `src/probos/avatars/blender_renderer.py`.

```python
class BlenderRenderer:
    def __init__(
        self,
        blender_path: str | None,
        timeout_s: int,
        drafts_dir: Path,
        max_vrm_size_bytes: int,
    ) -> None: ...
```

Resolution order for `blender_path`:

1. The constructor argument if non-empty.
2. `shutil.which("blender")`.
3. Raise `BlenderNotFoundError` (defined in this module) — typed exception with structured message.

Constructor performs no I/O beyond `shutil.which` (lazy resolution; subprocess is invoked only in `render`).

**Async only.** This module forbids `subprocess.run`; reviewer greps `subprocess\.run\(` across the diff and fails on any hit.

### E2 — `render(dsl, agent_id) -> Path` async method

**Same file.**

```python
async def render(self, dsl: AvatarDSL, agent_id: str) -> Path:
    """Run Blender headless, produce a .vrm. Return the output Path.

    Raises:
        BlenderNotFoundError, BlenderRenderError.
    """
```

Steps:

1. **Pre-check (before consuming a subprocess slot).** Verify either an operator-supplied `<avatars_dir>/_base_meshes/<dsl.body.type>.blend` exists OR `cfg.avatars.procedural_base_mesh_fallback` is `True`. If neither, raise `BlenderRenderError("no base mesh installed; DSL preserved at <drafts_dir>/<agent_id>.dsl.json")`. The intent layer (E4) wraps this into a non-success `IntentResult` so the agent's design is not lost.
2. Write the DSL to a temp YAML file under `drafts_dir`.
3. Resolve the absolute path of `_blender/render_avatar.py` (this repo's bundled script — see E3).
4. `proc = await asyncio.create_subprocess_exec(blender_path, "--background", "--factory-startup", "--python", str(render_script_path), "--", "--dsl", str(yaml_path), "--output", str(output_path), stdout=PIPE, stderr=PIPE)`.
5. `await asyncio.wait_for(proc.communicate(), timeout=self._timeout_s)`. On `TimeoutError`: `proc.terminate()`, `await asyncio.wait_for(proc.wait(), timeout=5)`, log structured warning (what/why/what-next), raise `BlenderRenderError`.
6. On non-zero exit: structured `logger.error` with stdout/stderr **tail** (last 2 KiB only — full output is sensitive in CI logs), raise `BlenderRenderError`.
7. On success: validate output (a) exists, (b) size ≤ `max_vrm_size_bytes`, (c) first 4 bytes equal `b"glTF"` (VRM is a glTF binary container). Any failure → `BlenderRenderError` and remove the partial file.
8. Output path: `<drafts_dir>/<agent_id>_<unix_ts>.vrm`. The atomic move to the canonical `<avatars_dir>/<agent_id>.vrm` is performed by E4's intent handler, not by this method.

**Async discipline:** if the implementation streams stdout/stderr into separate tasks, every `create_task(...)` reference is held in a local set and awaited before return. No fire-and-forget tasks.

### E3 — Bundled render script (runs INSIDE Blender's subprocess Python)

**New file:** `src/probos/avatars/_blender/render_avatar.py`.

Top-of-file:

```python
# pyright: reportMissingImports=false
# This file is executed ONLY inside the Blender subprocess Python where
# `bpy` is provided at runtime. Do NOT import this module from the dev venv.
import argparse, json, sys
from pathlib import Path
import bpy  # type: ignore[import-not-found]
```

Behavior:

1. Parse `--dsl <yaml>` and `--output <vrm>` from `sys.argv` (after `--`).
2. Read DSL YAML; convert to `AvatarDSL`-shaped dict (no Pydantic dependency inside Blender — duck-type).
3. Look for operator-supplied base mesh `<avatars_dir>/_base_meshes/<body_type>.blend`.
4. If absent AND the operator-supplied flag (passed via env var or another `--` arg) opts in to procedural fallback, build the **E10 capsule** (≤ 50 lines, see E10).
5. Apply hair/outfit/face shape-key parameters from the DSL.
6. **`expression_resting` bake:** set the chosen morph (e.g. `Fcl_MTH_A`) on **every face mesh** the export pipeline produces — direct mitigation of the AD-721 BF de4107b multi-mesh face-split issue. If the saturday06 add-on splits face meshes by material on export, every resulting face mesh receives the bake, not just the first.
7. Export VRM 1.0 via the saturday06 add-on operator.
8. Print a single structured success line to stdout and `sys.exit(0)`.

**Pytest exclusion (single mechanism, decided in dispatch §5 E3, restated here):**

- `pyproject.toml:93` already pins `testpaths = ["tests"]` — pytest never collects under `src/`. This is the primary mechanism.
- **DO NOT create** `src/probos/avatars/_blender/__init__.py` — directory must remain non-package so nothing under `src/probos/` can `from ._blender import render_avatar`.
- **Belt-and-suspenders:** add `collect_ignore_glob = ["**/_blender/**"]` to `tests/conftest.py`. Defense in depth.
- **`# pyright: reportMissingImports=false`** at the top of `render_avatar.py` for the `import bpy` line.
- **Forbidden:** adding a `[tool.pytest.ini_options] norecursedirs` entry. `testpaths` already constrains collection; `norecursedirs` is redundant noise.

The renderer entrypoint (E2) invokes the script by **absolute path** (`blender --background --python <abs path>`), not via Python import.

### E4 — `regenerate_avatar` intent + host agent

**New file:** `src/probos/agents/utility/avatar_agents.py`.

(Module name confirmed by Captain: matches the `web_agents.py` / `language_agents.py` plural-noun pattern used elsewhere under `agents/utility/`.)

```python
class AvatarRendererAgent(BaseAgent):
    intent_descriptors = [
        IntentDescriptor(
            name="regenerate_avatar",
            params={"agent_id": "str", "dsl_dict": "dict"},
            description="Render an approved AvatarDSL to VRM via the headless Blender backend.",
            requires_consensus=False,  # Captain approval (AD-721d) is the gate.
            tier="utility",
        )
    ]
```

Tier classification: `"utility"` (operates on the system, not for the user — matches the Agent Classification Framework).

Behavior of `act(intent: IntentMessage) -> IntentResult`:

1. Re-validate `intent.payload["dsl_dict"]` with `AvatarDSL.model_validate(...)` (defense in depth).
2. Short-circuit when `cfg.avatars.renderer_enabled is False`: return `IntentResult(success=False, error="renderer disabled")` without invoking subprocess.
3. Invoke `BlenderRenderer.render(dsl, agent_id)`. Catch `BlenderNotFoundError` and `BlenderRenderError` → `IntentResult(success=False, error=<typed reason>)`. Tier-2 log-and-degrade: AD-721d's DSL is already persisted; agent's design is not lost.
4. On success: `os.replace(<drafts_dir>/<agent_id>_<ts>.vrm, <avatars_dir>/<agent_id>.vrm)` — atomic on both POSIX and Windows. **No `.vrm.bak` rotation, no version history, no backup directory.** Cache invalidation = atomic overwrite.
5. Return `IntentResult(success=True, data={"vrm_path": str(canonical_path)})`.

**Wiring:** add `AvatarRendererAgent` to the runtime utility-pool roster the same way `web_agents` agents are wired. Verify-first against `src/probos/runtime.py` at build time (the dispatch's `_create_pools` reference may have shifted; do NOT edit a pool list that doesn't exist — grep for the analogous web/language utility wiring and copy that pattern). If no central pool list exists, wire via the standard utility-agent registration call site that `web_agents.py`/`language_agents.py` use.

**Hard-stop reminder:** if the dispatch's pool wiring assumption fails at HEAD, STOP and surface to the Captain — do NOT invent a new registration site.

### E5 — Config additions

**Modify:** `src/probos/config.py` — extend `AvatarsConfig` (lines 922–928).

```
===SEARCH===
class AvatarsConfig(BaseModel):
    # ... existing docstring ...
    enabled: bool = True
    avatars_dir: str = "data/avatars"
    max_vrm_size_bytes: int = 25 * 1024 * 1024
    fallback_to_parametric_on_error: bool = True
===REPLACE===
class AvatarsConfig(BaseModel):
    # ... existing docstring ... (preserve verbatim)
    enabled: bool = True
    avatars_dir: str = "data/avatars"
    max_vrm_size_bytes: int = 25 * 1024 * 1024
    fallback_to_parametric_on_error: bool = True
    # AD-721i: headless Blender renderer.
    blender_path: str = ""               # "" = search PATH via shutil.which
    blender_render_timeout_s: int = 180
    dsl_drafts_dir: str = "data/avatars/.drafts"
    # Wave 10 convention #14: transitional flag default-False; flip in a
    # follow-up AD once the renderer is exercised end-to-end.
    renderer_enabled: bool = False
    # Captain ruling 2026-05-09: capsule fallback default-on so v1 is
    # end-to-end without requiring operator-supplied base meshes.
    procedural_base_mesh_fallback: bool = True
===END REPLACE===
```

Naming note: `renderer_enabled` (adjective follows noun) matches the standing `AvatarsConfig.enabled` shape. Reviewer flags any `enabled_renderer`-style violation.

### E6 — `data/avatars/.drafts/` directory bootstrap

**New file:** `data/avatars/.drafts/.gitkeep` (empty).

Audit `.gitignore` to confirm `data/avatars/*.vrm` glob covers `.drafts/`. If the existing pattern is anchored at the directory level (e.g. `data/avatars/*.vrm` does NOT cover `data/avatars/.drafts/*.vrm`), add `data/avatars/**/*.vrm` to cover the subtree. Belt-and-suspenders is fine here — duplicate ignore patterns are harmless.

### E7 — Tests (Python, mocked subprocess)

**New file:** `tests/test_ad721i_renderer.py` — ≥ 12 tests. All `asyncio.create_subprocess_exec` calls are mocked. **NO real Blender invocation in this file.**

Required cases (one test each, minimum):

1. `test_blender_path_resolution_from_config` — explicit `blender_path` is used.
2. `test_blender_path_resolution_via_which` — empty config, `shutil.which("blender")` returns a path → used.
3. `test_blender_not_found_raises` — both above resolve to nothing → `BlenderNotFoundError`.
4. `test_no_base_mesh_and_no_capsule_fallback_returns_typed_error` — renderer pre-check fires.
5. `test_subprocess_timeout_terminates_and_raises` — mocked subprocess hangs; `wait_for` times out; `terminate()` is called; `BlenderRenderError`.
6. `test_subprocess_nonzero_exit_logs_stderr_tail_and_raises` — last 2 KiB of stderr appears in the log message.
7. `test_output_oversized_rejected` — file > `max_vrm_size_bytes` → raise + remove partial.
8. `test_output_bad_magic_rejected` — first 4 bytes are not `b"glTF"` → raise + remove partial.
9. `test_output_missing_after_success_exit_rejected` — exit 0 but no file at output path.
10. `test_atomic_replace_only_on_success` — the canonical `<agent_id>.vrm` is touched only when `render` returned successfully (intent-layer test).
11. `test_renderer_disabled_short_circuits_intent` — `cfg.avatars.renderer_enabled=False` → `IntentResult(success=False)` without subprocess invocation. (Mock asserts subprocess factory was never called.)
12. `test_no_subprocess_run_in_module` — AST scan of `blender_renderer.py` produces zero `Call` nodes whose function is `subprocess.run`. Defense against future regression.

### E8 — Tests (Blender integration smoke, opt-in)

**New file:** `tests/test_ad721i_blender_smoke.py` — exactly 1 test (or up to 2 if Builder finds the smoke needs split coverage).

```python
import shutil
import pytest
pytestmark = pytest.mark.skipif(
    shutil.which("blender") is None,
    reason="Blender not installed; AD-721i smoke skipped (BYOL).",
)
```

Test: render a minimal `AvatarDSL` (capsule fallback path), assert a `.vrm` is produced AND contains at least one `Fcl_MTH_A` morph (regression for the multi-mesh face-split BF — at least one face-mesh morph survived the export, which is the lowest-bar evidence the bake reached the export side). **Skips cleanly in CI without Blender.**

### E9 — Documentation

**New file:** `docs/development/avatar-renderer.md`.

Required sections:

- **Operator install steps.** Blender ≥ 4.0 download + saturday06 VRM-Addon-for-Blender ≥ 2.20 install + add-on enable. Concrete shell commands for Windows (winget) and Linux (apt / direct download).
- **Configuration.** `avatars.blender_path`, `avatars.renderer_enabled` (default-False; flip to True after smoke), `avatars.blender_render_timeout_s`, `avatars.procedural_base_mesh_fallback`, `avatars.dsl_drafts_dir`.
- **License notes.** Blender GPL-3.0 (subprocess-only boundary, BYOL); saturday06 add-on MIT (operator-installed, not vendored); Apache 2.0 repository ships zero 3D assets.
- **Base mesh sourcing guidance.** Operator-supplied path: `data/avatars/_base_meshes/<body_type>.blend` where `<body_type>` ∈ {`slim`, `average`, `stocky`}. Explicit warning: any base mesh the operator drops in-tree is the operator's licensing responsibility — the OSS repo neither audits nor distributes it.
- **Troubleshooting.** Common failure modes:
  - "Blender not in PATH" → set `avatars.blender_path` explicitly.
  - "Add-on not enabled" → enable saturday06 in Blender preferences, save startup file.
  - "Render timeout" → raise `avatars.blender_render_timeout_s`.
  - "Output rejected — oversized / bad magic" → likely the add-on emitted a non-VRM glTF; check add-on version.

### E10 — Procedural humanoid base-mesh fallback

**Same file as E3** (`src/probos/avatars/_blender/render_avatar.py`).

When no operator-supplied `<body_type>.blend` is present AND `cfg.avatars.procedural_base_mesh_fallback=True` (default-on per Captain ruling 2026-05-09):

- Build a **minimal capsule** with `bpy.ops.mesh.primitive_cylinder_add` + `bpy.ops.mesh.primitive_uv_sphere_add` for the head.
- Apply a single bone armature (required for VRM export compliance).
- Export VRM via the saturday06 add-on.

**Hard floor on complexity:** ≤ 50 lines. Reviewer fails the prompt if the capsule grows past 50 lines or imports anything beyond `bpy.ops.mesh`, `bpy.ops.object`, and the saturday06 VRM-Addon export hooks. **This is intentionally crude** — it is the v1 "smoke test passes without bundled assets" path, not a production avatar. AD-721i-1's license-audited starter pack is where the realistic humanoid work belongs.

## 7. Hard-stop conditions (verbatim from `WAVE-134-DISPATCH.md` §8)

1. **Phantom DSL field.** If AD-721i's tests reference an `AvatarDSL` field that the model doesn't actually define, STOP — do not silently add the field.
2. **Subprocess discipline regression.** Any `subprocess.run` introduced under `src/probos/avatars/` is a hard stop. `asyncio.create_subprocess_exec` only.
3. **`exec`/`eval`/`compile` on DSL content.** Hard stop. Reviewer greps the diff and fails the prompt.
4. **Working-tree integrity.** Pre-flight `git diff --numstat` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to the Captain.
5. **Multi-mesh face-split regression.** AD-721d's D9 Vitest fails OR E8's smoke (when Blender is present) shows zero `Fcl_MTH_A` morphs on the exported VRM → STOP.
6. **`bpy` imported at top level outside `_blender/`.** Hard stop. `bpy` only exists in the Blender subprocess Python; importing it in any module under `src/probos/` (other than `_blender/render_avatar.py`) fails the dev-venv test gate by definition.
7. **Operator-supplied 3D assets accidentally committed.** Reviewer audits the diff for any `.vrm`, `.blend`, `.fbx`, `.glb` file in `data/avatars/_base_meshes/` or anywhere else. Files under those names ship only `.gitkeep`.
8. **PROGRESS.md stale "current highest AD" line.** Pre-push: Builder MUST update `PROGRESS.md` line 13 (or wherever the live `current highest AD: AD-698` string lives — grep if displaced) to `current highest AD: AD-721i`. Single-line edit, folded into this wave's commit chain.

## 8. Forward markers

- **AD-721i-1** — license-audited starter asset pack (CC0/Apache base meshes, hair, outfits). File at gate-3.
- **AD-721i-2** — VRoid Studio CLI alternative backend evaluation. File at gate-3 if Captain wants the option.
- **AD-721j** — Computer Use Blender control (already filed; outside-DSL artistry).

## 9. What this AD does NOT change

- The DSL schema (owned by AD-721d).
- `AppearanceProfile` persistence (read-only consumer).
- The `CrewVRM` runtime expression layer (the renderer bakes morphs at export time; runtime layer untouched).
- Any third-party 3D asset shipped in-repo (zero assets ship).
- The `addopts`, `norecursedirs`, or `testpaths` of `pyproject.toml` beyond what's already present.

## 10. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specific checkpoints (Builder confirms each in the build report):

- Cloud-Ready Storage — no new persistence path; consumes existing `_resolve_avatars_dir`.
- Defense in Depth — DSL re-validated at intent layer + at renderer entry; output path validated; size + magic-bytes checks.
- Three-tier exceptions — `BlenderNotFoundError` and `BlenderRenderError` are typed; intent layer log-and-degrades (Tier 2); renderer layer propagates typed errors (Tier 3 to the intent boundary).
- Async discipline — `create_subprocess_exec` only; `subprocess.run` forbidden; task references held; cancellation handled (`terminate` + bounded `wait`).
- No private-attr access — all extension via public `AvatarsConfig` fields and public renderer constructor.
- Type annotations — all public methods fully typed.
- Logging quality — every log message has what/why/what-next context, with stdout/stderr tail (last 2 KiB only) on failure.
- Layer discipline — `agents/utility/` is the correct tier site for the host agent.

## 11. Acceptance criteria

- All ≥ 12 mocked Python tests pass; the 1 Blender smoke test skips cleanly without Blender (and passes with Blender installed).
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` green; `cd ui && npx vitest run` green (cross-AD: AD-721d's Vitest tests are part of the wave gate).
- `tests/test_ad721i_renderer.py` runs in isolation on a machine WITHOUT Blender and passes.
- Files touched (target list):
  - **New:** `src/probos/avatars/blender_renderer.py`, `src/probos/avatars/_blender/render_avatar.py`, `src/probos/agents/utility/avatar_agents.py`, `data/avatars/.drafts/.gitkeep`, `docs/development/avatar-renderer.md`, `tests/test_ad721i_renderer.py`, `tests/test_ad721i_blender_smoke.py`.
  - **Modified:** `src/probos/config.py`, `src/probos/runtime.py` (utility-pool wiring — verify-first), `tests/conftest.py` (collect_ignore_glob), `.gitignore` (audit only), `PROGRESS.md` (single-line `current highest AD` update — coordinate with AD-721d's edit; whichever Builder commits second leaves the line correct).
- GH issue [#537](https://github.com/seangalliher/ProbOS/issues/537) closed with a one-line commit reference.
- Forward markers AD-721i-1, AD-721i-2 filed at gate-3.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
