# WAVE 134 DISPATCH — Agent-authored avatar appearance pipeline (AD-721d + AD-721i)

**Wave:** 134
**Mode:** main
**Depends on:** 133
**Builder required:** yes
**Issues to close:** [#531](https://github.com/seangalliher/ProbOS/issues/531) (AD-721d), [#537](https://github.com/seangalliher/ProbOS/issues/537) (AD-721i)
**Date:** 2026-05-09

---

## 1. Goal

Close the loop on "agent picks own face." The agent reflects on its personality, proposes an `AvatarDSL` artifact (structured YAML — not code), the Captain reviews and approves, and a headless-Blender backend (operator-installed) deterministically renders the DSL to a `.vrm` that ProbOS already knows how to display via AD-721's `CrewVRM` popout. The DSL persists even when Blender is absent — agent-side proposal cycle is decoupled from renderer availability.

## Summary

This wave pairs two prompts that ship together but are independently testable. **AD-721d** is the runtime/UI side: extends `AppearanceProfile` with an optional `dsl: AvatarDSL | None` field, adds an `instructions`-driven appearance-design capability to CognitiveAgent (mirroring AD-718a's voice profile self-design pattern), persists DSL proposals through the existing `ProfileStore` SQLite layer, and surfaces a "Design avatar" affordance on the profile card that triggers proposal → Captain approval → DSL persistence. **AD-721i** is the headless backend: a new `src/probos/avatars/blender_renderer.py` module that wraps `asyncio.create_subprocess_exec` around `blender --background --python …` to produce a `.vrm` from an `AvatarDSL` artifact. Blender is GPL — we treat it as an OS-level subprocess (BYOL, operator brings Blender ≥ 4.0 + saturday06 VRM Add-on). When Blender is absent, AD-721d still functions: the DSL is persisted; `CrewVRM` falls back to parametric rendering until an operator runs the renderer or installs Blender.

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found | Disposition |
|---|---|---|
| `AppearanceProfile` (`src/probos/crew_profile.py:129-153`) | Already exists with `vrm_url`, `expression_overrides`, `color_palette_hint`. AD-721 v1. | **Extend** with optional `dsl: AvatarDSL \| None`. Do NOT repurpose `expression_overrides` for DSL data — it serves a different post-render runtime layer. |
| `AvatarsConfig` (`src/probos/config.py:922-928`) | `enabled=True`, `avatars_dir`, `max_vrm_size_bytes=25 MB`, `fallback_to_parametric_on_error`. | **Extend** with `blender_path: str = ""` (empty = "search PATH"), `blender_render_timeout_s: int = 180`, `dsl_drafts_dir: str = "data/avatars/.drafts"`. |
| AD-721 BF #539 — `_resolve_avatars_dir` (`src/probos/routers/system.py:641`) | Path traversal-safe avatar resolution rooted under `_platform_data_dir()`. | **Reuse** for `dsl_drafts_dir` and rendered `.vrm` output paths — same threat surface. |
| AD-718a forward marker (agent-authored voice profile) | Mirror pattern: agent reflects on personality → proposes structured profile → Captain approves. | **Mirror this shape exactly** for `propose_appearance()`. AD-718a is in Wave 136 — AD-721d goes first, AD-718a copies the pattern in its prompt body. |
| `AgentDesigner` (`src/probos/cognitive/agent_designer.py`) | LLM-generated *executable code* with `CodeValidator` static analysis, sandbox boot, probationary trust. | **Pattern absorption only** — DSL is *data*, not code. `CodeValidator` does NOT apply. Trust gating reduces to "Captain explicitly approves the proposed DSL artifact" — same gate as voice profile. |
| `asyncio.create_subprocess_exec` usage (`src/probos/cognitive/builder.py:2534`, `src/probos/worktree_manager.py:52`) | Established async subprocess pattern. | **Reuse** for Blender invocation. Forbid `subprocess.run` in `blender_renderer.py`. |
| Anthropic Cowork "agent designs own appearance" demo + Blender Connector tutorial | Pattern reference. | **Pattern absorption only.** Agent writes DSL; we wrote the DSL schema and the renderer. No Anthropic code/SDK absorbed. |
| `@pixiv/three-vrm` (already installed, MIT) | Renders the produced `.vrm`. | No change — AD-721 v1 already wires this. |
| `saturday06/VRM-Addon-for-Blender` | MIT license, supports VRM 1.0 export from Blender 4.x. | **Operator-installed.** Documented as a prerequisite alongside Blender. Not vendored. |
| Blender (GPL-3.0) | Subprocess-only boundary. Apache 2.0 repo never embeds `bpy` as a Python library; `bpy.ops` runs only inside the subprocess Blender spawned. | **Subprocess BYOL.** Operator brings `blender` binary; Apache 2.0 is preserved (subprocess invocation is OS-level, not derivative work). |
| Base mesh / hair / outfit assets (issue #537 D3) | Issue calls for "small set of CC0 / commissioned-Apache base meshes." | **DEFERRED to AD-721i-1** (see §7). v1 ships ZERO third-party 3D assets — operator either provides their own base mesh in `data/avatars/_base_meshes/` or uses the parametric fallback. License audit of any candidate base meshes is its own AD. |
| `data/avatars/` directory | `.gitkeep` ships; `.gitignore` already excludes `*.vrm`. | **Reuse.** New subdirectories `data/avatars/.drafts/` (DSL drafts + draft VRMs) and `data/avatars/_base_meshes/` (operator-supplied) inherit the same ignore. |

**Top-level license posture:** OSS Apache 2.0 stays Apache 2.0. Blender (GPL) is shell-out only. `VRM-Addon-for-Blender` (MIT) is operator-installed. No commercial APIs. Renders are local-only (`data/avatars/`). Matches the standing OSS-vs-paid rule (BYOL + pattern absorption).

---

## 3. Engineering-principles checklist

Builder must verify each of these in the per-prompt acceptance criteria. Reviewer flags any miss as **Required**.

| Principle (from `.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Cloud-Ready Storage** | `AvatarDSL` persistence; rendered VRMs | DSL stored on `AppearanceProfile.dsl` → flows through existing `ProfileStore` SQLite path. Rendered `.vrm` lands under `_resolve_avatars_dir()` only. No new direct `aiosqlite.connect()`. |
| **Defense in Depth** | DSL flow LLM → schema → subprocess → output | (1) Pydantic v2 validator on `AvatarDSL` (typed fields, value bounds, allowed-enum strings only). (2) Renderer re-validates the DSL before invoking `bpy`. (3) Output path is `_resolve_avatars_dir`-resolved. (4) Output `.vrm` size ≤ `max_vrm_size_bytes`. (5) Output file's first 4 bytes verified as VRM glTF magic (`glTF`). |
| **Fail Fast / Tier-2 log-and-degrade** | Renderer absent or fails | If Blender is missing or returns non-zero, log a structured warning *with* (what failed, why it matters, what happens next), **persist the DSL anyway**, and let `CrewVRM` fall back to parametric. Agent's proposal is not lost. |
| **Async discipline** | Subprocess invocation + task references | `asyncio.create_subprocess_exec` only. NO `subprocess.run`. Any `create_task` for streaming stdout/stderr stores the task reference. Cancellation handled (`proc.terminate()` + `await proc.wait()` with timeout). |
| **No private-attr access** | Adding `dsl` field | Goes on the public `AppearanceProfile` dataclass, with `to_dict`/`from_dict` extended symmetrically. No reaching into `_private_attr` of `ProfileStore` or `CrewProfile`. |
| **Test gates** | Both prompts | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad721d_*.py tests/test_ad721i_*.py -v -n 0` AND full gate `pytest tests/ -q -n 4 --dist=loadfile` per BUILDER-EXECUTION-PLAN.md. AD-721i Blender integration test uses `pytest.mark.skipif(shutil.which("blender") is None, …)`. |
| **No emoji in UI** (HXI Design Principle #3) | "Design avatar" button + approval bar | Stroke-based inline SVG. `strokeWidth: 1.5`. Active amber `#f0b060`. Reviewer fails the prompt on any emoji. |
| **CrewVRM multi-mesh face-split BF** (de4107b) | DSL-controlled `expression_resting` | If the DSL specifies a resting expression, AD-721d's render path (and any post-render runtime expression layer) MUST drive **every face mesh** carrying the target morph (`Fcl_MTH_*`, etc.), not the expression manager binding. Explicit Vitest regression test required: spawn a 3-face-mesh fixture, assert all three mesh `morphTargetInfluences` indices update. |
| **Storage abstraction (Protocol)** | Any new persistence path | Reuse `ProfileStore`'s existing path. If a Builder is tempted to add a sidecar SQLite table, fail the prompt — DSL belongs on `AppearanceProfile.dsl`. |
| **AgentDesigner / CodeValidator decoupling** | DSL is data, not code | DSL is YAML/JSON only. **Forbid** any `exec`, `eval`, `compile`, or `importlib.import_module` on DSL content. Reviewer greps the diff. The LLM proposal step in D3 MUST request **strict JSON / structured-output mode** from the LLM tier (e.g. `response_format={"type": "json_object"}` for OpenAI-compatible endpoints, or a constrained-grammar / tool-call shape). Free-form text + YAML parse on raw LLM output is a known prompt-injection / parser-confusion surface and is **forbidden**. If the configured LLM tier does not advertise JSON mode, the prompt body MUST harden the fallback path: `yaml.safe_load` only after a hard size cap (≤ 16 KiB), max-depth guard (reject documents nesting > 8 levels), cycle/anchor-bomb rejection (`yaml.safe_load` already blocks tag execution; additionally reject any document containing `&` anchors or `*` aliases for v1), then Pydantic v2 validation against the `AvatarDSL` allowed-enum strings. Anything outside the enum surface is rejected at the schema layer, never coerced. |

---

## 4. AD-721d scope — Agent-authored appearance pipeline

**Issue:** [#531](https://github.com/seangalliher/ProbOS/issues/531). Forward marker from AD-721. Captain decision 2026-05-09 refines: agent-side reflection cycle → DSL proposal, Counselor reviews, Captain approves.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | `AvatarDSL` Pydantic model | `src/probos/avatars/dsl.py` (new) — note: this MODULE is created in AD-721d, even though AD-721i also lives under `src/probos/avatars/`. | Pydantic v2 model. Fields: `body{type, height_cm}`, `hair{style, color_hsl}`, `face{warmth, jaw, eyes}`, `outfit{style, primary_color, accents}`, `expression_resting`, `notes`. All enums constrained to allowed-string lists. Value bounds via `field_validator`. **Defaults required for every field — `AvatarDSL()` with no args must succeed.** |
| **D2** | `AppearanceProfile.dsl` field | `src/probos/crew_profile.py` (modify lines 129-153) | Add `dsl: AvatarDSL \| None = None`. Extend `to_dict`/`from_dict` symmetrically. Round-trip JSON test required. |
| **D3** | `propose_appearance()` capability on CognitiveAgent | `src/probos/cognitive/cognitive_agent.py` (extend) — pattern mirrors how `instructions`-driven LLM reasoning works in AgentDesigner. | New async method on `CognitiveAgent`: takes the agent's own personality/standing-orders/recent-trust-history, hands them to the agent's `instructions`-tier LLM with a hardened system prompt **using strict JSON / structured-output mode** (see §3 row "AgentDesigner / CodeValidator decoupling" for the exact requirement and fallback rules). The DSL is parsed with `yaml.safe_load` ONLY after the response has been size-capped (≤ 16 KiB); subsequent Pydantic validation rejects anything outside the allowed-enum strings; **no `compile`, `exec`, `eval`, or `importlib.import_module` is permitted on any LLM-derived artifact at any layer of the stack. Reviewer greps the diff.** Returns a validated `AvatarDSL` or raises `AppearanceProposalError` with a structured reason. |
| **D4** | DSL persistence | `src/probos/profile_store.py` (verify-first; AD-721 already round-trips `appearance` through this layer) | `appearance` round-trip test extended to assert `dsl` survives. No new SQLite table. |
| **D5** | "Design avatar" UI affordance | `ui/src/components/profile/AgentProfilePanel.tsx` (extend) | Inline SVG button (`strokeWidth: 1.5`, amber when active). Click → calls a new HXI endpoint that triggers `propose_appearance`. Returns the proposed DSL for Captain review. |
| **D6** | Captain approval surface | `ui/src/components/profile/CrewAvatarPopout.tsx` (extend) — adds an approval bar inside the existing modal. | Approve / Request revisions / Reject. Approve persists DSL to `AppearanceProfile.dsl` via the existing profile-update endpoint. **No emoji in icons.** |
| **D7** | HXI endpoints | `src/probos/routers/agents.py` (confirmed at HEAD: existing `@router.put("/{agent_id}/voice-profile")` at L194 from AD-718; appearance endpoints **mirror that placement** in the same file). | `POST /agents/{agent_id}/appearance/propose` (returns DSL) and `PUT /agents/{agent_id}/appearance` (persists DSL after Captain approval — `PUT` mirrors the AD-718 voice-profile verb choice). Both feature-gated on `cfg.avatars.enabled`. The mounted router prefix is owned by the FastAPI app — endpoint decorators stay relative (`/{agent_id}/...`), matching every other route in `agents.py`. |
| **D8** | Renderer cache awareness on the read path | `src/probos/routers/agents.py` (`appearance` field on profile endpoint) | If `vrm_url` is empty AND `dsl` is set AND a rendered cache exists at `<avatars_dir>/<agent_id>.vrm`, the response synthesises `vrm_url` to point at the cache. Otherwise `vrm_url=""` → parametric fallback. **No new endpoint** — extend the existing one. |
| **D9** | Multi-mesh face-split regression test | `ui/src/__tests__/CrewVRM.expressionResting.test.tsx` (new) | Vitest fixture VRM with 3 face meshes; assert all 3 `morphTargetInfluences` indices update when DSL `expression_resting=gentle_smile`. Direct regression of AD-721 BF de4107b. |
| **D10** | Tests — Python | `tests/test_ad721d_avatar_dsl.py` (new) — boundary cases on Pydantic; `tests/test_ad721d_propose_appearance.py` (new) — mocks LLM, asserts DSL parse + persistence; `tests/test_ad721d_endpoints.py` (new). | Each public method gets happy + error + edge case. Target ≥ 18 tests across the three files. |
| **D11** | Tests — UI | `ui/src/__tests__/AgentProfilePanel.designAvatar.test.tsx` (new) and the regression in D9. | Component-level coverage of the design button + approval bar. |

### Counselor-as-design-partner constraint
AD-721 v1 named Counselor (Echo) the first design partner. AD-721d's first end-to-end exercise should be Counselor proposing her own DSL. Architect notes this in the prompt body but does not block the Builder on it — it is a post-build smoke-test note for the Captain, not a code deliverable.

### Mock the renderer
AD-721d's Python tests must mock the AD-721i renderer. AD-721d does **not** depend on Blender being installed in CI or on the developer's machine. Builder must prove this by running the AD-721d test file in isolation on a machine without Blender.

---

## 5. AD-721i scope — DSL → Blender VRM renderer (headless backend)

**Issue:** [#537](https://github.com/seangalliher/ProbOS/issues/537). Pair with AD-721d.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **E1** | `BlenderRenderer` async class | `src/probos/avatars/blender_renderer.py` (new) | Constructor: `BlenderRenderer(blender_path: str \| None, timeout_s: int, drafts_dir: Path)`. Resolves `blender_path` via the configured value, then `shutil.which("blender")`, then raises `BlenderNotFoundError`. **Async only** — uses `asyncio.create_subprocess_exec`. NO `subprocess.run`. |
| **E2** | `render(dsl: AvatarDSL, agent_id: str) -> Path` async method | same file | Writes the DSL to a temp YAML, invokes `blender --background --factory-startup --python <render_script> -- --dsl <yaml> --output <vrm>`. On non-zero exit or timeout: structured `logger.error` with stdout/stderr tail, raises `BlenderRenderError`. On success: validates output `.vrm` exists, size ≤ `max_vrm_size_bytes`, first 4 bytes are `glTF`. Output lands at `<drafts_dir>/<agent_id>_<unix_ts>.vrm`. |
| **E3** | Bundled render script | `src/probos/avatars/_blender/render_avatar.py` (new — runs INSIDE Blender's subprocess Python) | Reads DSL YAML, uses `bpy.ops` + `saturday06` VRM-Addon. Reads operator-supplied base mesh from `<avatars_dir>/_base_meshes/<body_type>.blend` if present; otherwise falls back to the **E10 procedural humanoid capsule** (see below) so the v1 path is end-to-end without any bundled assets. Applies hair/outfit/face shape-key parameters from the DSL. Exports VRM 1.0. **This file is shipped in the repo but only ever executed by the Blender subprocess — its imports of `bpy` are explicitly OK** (Blender provides `bpy` at runtime). **Pytest exclusion (single mechanism, decided here):** repo-level `[tool.pytest.ini_options]` already pins `testpaths = ["tests"]` (pyproject.toml L93), so files under `src/probos/avatars/_blender/` are **never collected** by pytest in the first place. Belt-and-suspenders: (a) DO NOT create `src/probos/avatars/_blender/__init__.py` — the directory is intentionally non-package so nothing under `src/probos/` can `from ._blender import render_avatar`; (b) add `collect_ignore_glob = ["**/_blender/**"]` to `tests/conftest.py` for defense in depth; (c) add `# pyright: reportMissingImports=false` at the top of `render_avatar.py` for the `import bpy` line. Builder MUST NOT add a `[tool.pytest.ini_options] norecursedirs` entry — `testpaths` already constrains collection and adding `norecursedirs` is redundant noise. The renderer entrypoint invokes the script by absolute path (`blender --background --python <abs path to render_avatar.py>`), not via Python import. **Renderer pre-check:** the renderer (E2) MUST verify a base mesh path is resolvable BEFORE consuming a subprocess slot — if neither operator-supplied `<body_type>.blend` exists NOR the E10 capsule fallback is enabled, the intent (E4) returns `IntentResult(success=False, error="no base mesh installed; DSL preserved at <drafts_dir>/<agent_id>.dsl.json")` so the agent's design is not lost. |
| **E4** | `regenerate_avatar` intent + host agent | `src/probos/agents/utility/avatar_agents.py` (new — confirmed registration pattern at HEAD: every host agent declares `intent_descriptors = [...]` on a `BaseAgent` subclass; e.g. `src/probos/agents/utility/web_agents.py` L82, L125, L169, L221; `src/probos/agents/utility/language_agents.py` L32, L55. **`agent_designer.py` only contains string-template `IntentDescriptor(...)` literals (L119, L155) — those are templates emitted into LLM-generated agent code, NOT real registrations. Builder MUST NOT add the descriptor there.**) | New `AvatarRendererAgent(BaseAgent)` in the new `agents/utility/avatar_agents.py` module, classified `tier="utility"` (operates on the system, not for the user — matches Agent Classification Framework). Class-level `intent_descriptors = [IntentDescriptor(name="regenerate_avatar", params={"agent_id": "str", "dsl_dict": "dict"}, description="Render an approved AvatarDSL to VRM via the headless Blender backend.", requires_consensus=False, tier="utility")]`. (`requires_consensus=False` because Captain approval is the gate; renderer is deterministic.) Wire into the runtime pool roster the same way other utility agents are wired (verify-first against `src/probos/runtime.py` pool creation when drafting; do not edit a pool list that doesn't exist). On success, **moves draft from `<drafts_dir>/<agent_id>_<ts>.vrm` to `<avatars_dir>/<agent_id>.vrm` via `os.replace`** (see §6 for the atomic-overwrite contract). |
| **E5** | Config additions | `src/probos/config.py` `AvatarsConfig` (extend lines 922-928) | `blender_path: str = ""`, `blender_render_timeout_s: int = 180`, `dsl_drafts_dir: str = "data/avatars/.drafts"`, `renderer_enabled: bool = False` (Wave 10 convention #14 — transitional flag default-False; **named `renderer_enabled` (not `enabled_renderer`) to match the standing `AvatarsConfig.enabled` pattern — adjective follows noun**), `procedural_base_mesh_fallback: bool = True` (E10 — capsule-fallback default-on so v1 is end-to-end without operator base meshes). When `renderer_enabled=False`, `regenerate_avatar` returns `IntentResult(success=False, error="renderer disabled")` without invoking the subprocess. |
| **E6** | `data/avatars/.drafts/` directory bootstrap | `data/avatars/.drafts/.gitkeep` (new) + `.gitignore` audit | Confirm `data/avatars/*.vrm` ignore pattern covers drafts subdir. |
| **E7** | Tests — Python | `tests/test_ad721i_renderer.py` (new) — mocks `asyncio.create_subprocess_exec`, asserts: (a) Blender-absent path raises `BlenderNotFoundError`, (b) timeout path raises `BlenderRenderError` and terminates the process, (c) non-zero exit logs stderr tail, (d) output validation rejects oversized files, (e) output validation rejects files that aren't VRM (bad magic bytes), (f) atomic rename happens only on success. | Target ≥ 12 tests. **No real Blender call.** |
| **E8** | Tests — Blender integration smoke | `tests/test_ad721i_blender_smoke.py` (new) | `pytest.mark.skipif(shutil.which("blender") is None, reason="Blender not installed")`. Renders a minimal DSL using the bundled render script. Asserts a `.vrm` is produced. **Skips cleanly in CI without Blender.** This is the only test that actually invokes a subprocess. |
| **E9** | Documentation | `docs/development/avatar-renderer.md` (new) | Operator install steps for Blender + saturday06 add-on. License notes (Blender GPL — subprocess-only; saturday06 MIT). Base mesh sourcing guidance ("operator-supplied; no third-party 3D assets ship in this repo"). Troubleshooting (path not in PATH; add-on not enabled; render timeout). |
| **E10** | Procedural humanoid base-mesh fallback | `src/probos/avatars/_blender/render_avatar.py` (within E3 script — keep complexity floor LOW: ~30 lines max) | When no operator-supplied `<body_type>.blend` is present AND `cfg.avatars.procedural_base_mesh_fallback=True` (E5), the script builds a **minimal capsule** with `bpy.ops.mesh.primitive_cylinder_add` + `primitive_uv_sphere_add` for head, applies a single bone armature for VRM export compliance, and exports. **This is intentionally crude** — it is the v1 "smoke test passes without bundled assets" path, not a production avatar. Builder MUST NOT spend effort sculpting a realistic humanoid here — that work belongs to AD-721i-1's license-audited starter pack. Reviewer fails the prompt if the capsule fallback grows past ~50 lines or imports anything beyond `bpy.ops.mesh` / `bpy.ops.object` / VRM-Addon export hooks. |

### Out-of-scope inside AD-721i
- Bundled base meshes (deferred to AD-721i-1 — see §7).
- VRoid Studio CLI alternative (issue #537 mentions it as a research note; not a v1 path).
- Render preview UI in HXI (deferred to AD-721d-1; v1 just exposes the rendered `.vrm` via the existing avatar route).

---

## 6. Cross-AD integration points

| Integration point | AD-721d responsibility | AD-721i responsibility |
|---|---|---|
| `AvatarDSL` schema | Owns the dataclass + Pydantic validator (`src/probos/avatars/dsl.py`). | Imports and re-validates inside the renderer (defense in depth). |
| Renderer invocation | Tests **mock** the renderer. | Provides the renderer; surfaces a typed result that AD-721d's tests can mock against. |
| `AppearanceProfile.dsl` flow | Owns the field, persistence, endpoints. | Reads it as input only (never writes back to `AppearanceProfile`). |
| `<agent_id>.vrm` cache | Reads the cache (D8). | Writes the cache via atomic rename (E4). **Atomic-overwrite contract:** rename uses `os.replace` (atomic on both POSIX and Windows). On a re-render of the same `agent_id`, the previous `.vrm` is overwritten in place. **There is no `.vrm.bak` rotation, no version history, no backup directory in v1.** Builder MUST NOT add such a system on a hunch — if the Captain wants render history, that is a forward-marker AD, not this wave. |
| Config | Consumes `cfg.avatars.enabled` for endpoints. | Consumes `cfg.avatars.enabled_renderer`, `blender_path`, `blender_render_timeout_s`, `dsl_drafts_dir`. |
| **Multi-mesh face-split BF** | **D9 regression test is mandatory** (Vitest, runtime-side). | Render script (E3) MUST set `expression_resting` morphs at *bake time* on the exported VRM such that downstream `CrewVRM` runtime expression layer can drive every face mesh via the same morph names AD-721 BF already uses (`Fcl_MTH_*`). If the chosen Blender VRM Add-on splits face meshes by material on export, E3 must write the bake to **every** resulting face mesh, not just the first. **Builder verifies this with a manual export inspection** — the smoke test E8 asserts at least one `Fcl_MTH_A` morph exists on the output. |

### Build order
AD-721d's prompt is independently buildable and ships first within the wave. AD-721i builds on top (imports `AvatarDSL` from `src/probos/avatars/dsl.py`). Both are committed in the same wave; merge order is d → i. The Builder may interleave commits if convenient but must not push i before d.

---

## 7. Out-of-scope / deferred to later waves

| Deferred item | Why deferred | Where it lands |
|---|---|---|
| Bundled CC0/Apache base meshes, hair, outfits | License audit per asset is its own AD. Issue #537 D3 is too broad for this wave. v1 ships ZERO 3D assets — operator supplies via `data/avatars/_base_meshes/`. | **AD-721i-1** — license-audited starter asset pack (forward marker, file as GH issue at gate-3). |
| Captain Edit Avatar UI (edits DSL directly) | Already filed as AD-721a. | AD-721a (separate wave). |
| Rendered-draft preview surface in HXI before approval | Adds ~3 React components + WebSocket plumbing. Out of scope for v1. | **AD-721d-1** — draft preview + revisions cycle (forward marker, file at gate-3). |
| Re-approval / DSL regeneration cache invalidation | When the Captain re-approves an updated DSL (DSL bytes differ from the cached one), the existing rendered VRM is invalidated by the SAME `regenerate_avatar` intent that produced the original. Cache invalidation = atomic overwrite via `os.replace` (see §6). No diff/merge UI in v1. | Implicitly handled by E4 — no separate AD needed. |
| Computer Use Blender control (outside-DSL artistry) | Issue #537 explicitly defers this to AD-721j. | AD-721j (forward marker, already filed). |
| VRoid Studio CLI path | Alternative backend; v1 picks Blender + saturday06. | **AD-721i-2** — VRoid backend evaluation (forward marker, file at gate-3 if Captain wants the option). |
| Phoneme-driven mouth shapes set inside the DSL | AD-721b owns lip-sync. The DSL's `expression_resting` is rest-state only — runtime visemes still flow through AD-721b's pipeline. | AD-721b (already promoted, separate wave). |

**Scope-reframe note (Wave 10 lesson #5):** AD-721d's draft scope (D1–D11, ~18 tests) is at the upper edge of a single-wave AD. If the prompt drafter finds in their final research pass that the Captain-approval flow needs richer revision-history or a multi-step approval state machine, defer those to AD-721d-1 explicitly and ship a **single-shot approve/reject** v1.

---

## 8. Hard-stop conditions for the Builder

Standard hard-stop rules from BUILDER-EXECUTION-PLAN.md apply, **plus**:

1. **Phantom DSL field.** If AD-721d's tests reference an `AvatarDSL` field that the model doesn't actually define, STOP — do not silently add the field.
2. **Subprocess discipline regression.** Any `subprocess.run` introduced under `src/probos/avatars/` is a hard stop. `asyncio.create_subprocess_exec` only.
3. **`exec`/`eval`/`compile` on DSL content.** Hard stop. Reviewer greps the diff and fails the prompt.
4. **Working-tree integrity.** Pre-flight `git diff --numstat` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to the Captain (per `/memories/probos-architect-learnings.md` 2026-05-08 incident).
5. **Multi-mesh face-split regression.** D9's Vitest fails → STOP. This is the exact AD-721 BF de4107b shape and we will not regress it.
6. **`bpy` imported at top level outside `_blender/`.** Hard stop. `bpy` only exists in the Blender subprocess Python; importing it in any module under `src/probos/` (other than `_blender/render_avatar.py`) fails the test gate by definition because the dev venv does not have `bpy`.
7. **Operator-supplied 3D assets accidentally committed.** Reviewer audits the diff for any `.vrm`, `.blend`, `.fbx`, `.glb` file in `data/avatars/_base_meshes/` or anywhere else. Files under those names ship only `.gitkeep`.
8. **PROGRESS.md L11 stale "current highest AD" line.** Pre-flight: before the final push of this wave, Builder MUST update `PROGRESS.md` line 11 from `current highest AD: AD-698` to `current highest AD: AD-721i`. Single-line edit, folded into the wave's commit chain (NOT a separate BF). If line 11 is no longer the location of that string, grep the file for `AD-698` and update the live line. Reviewer fails the wave if the line is still stale post-merge.

---

## 9. Acceptance criteria

- **Test count target:** AD-721d ≥ 18 Python tests + 2 Vitest tests; AD-721i ≥ 12 Python tests + 1 Blender smoke test (skipped without Blender). Wave gate: full `pytest tests/ -q -n 16 --dist=loadfile` is green (matches `BUILDER-EXECUTION-PLAN.md` L33 standing rule and the addopts pinned in `pyproject.toml` L93) AND `cd ui && npx vitest run` is green. **Fallback:** if the dev machine regresses on `-n 16` (worker crashes from heavy fixtures), drop to `-n 8` and document the regression in the build report — do NOT silently switch to `-n auto` (xdist + ChromaDB fixture concurrency is the documented BF #466 failure mode).
- **Files touched (target list — drafter refines):**
  - New: `src/probos/avatars/__init__.py`, `src/probos/avatars/dsl.py`, `src/probos/avatars/blender_renderer.py`, `src/probos/avatars/_blender/render_avatar.py`, `data/avatars/.drafts/.gitkeep`, `docs/development/avatar-renderer.md`, plus 4 new test files and 2 new Vitest files.
  - Modified: `src/probos/crew_profile.py`, `src/probos/config.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/profile_store.py` (verify-first), `src/probos/routers/agents.py`, `ui/src/components/profile/AgentProfilePanel.tsx`, `ui/src/components/profile/CrewAvatarPopout.tsx`, `ui/src/store/types.ts`.
- **GH issues to close:** [#531](https://github.com/seangalliher/ProbOS/issues/531) (AD-721d), [#537](https://github.com/seangalliher/ProbOS/issues/537) (AD-721i).
- **Forward markers to file at gate-3 (BUILDER-EXECUTION-PLAN Post-Sweep step 6):** AD-721d-1 (draft preview + revision cycle), AD-721i-1 (starter asset pack), AD-721i-2 (VRoid backend evaluation).
- **Engineering principles compliance line (mandatory in each prompt):** *"Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."*
- **Phantom-API pre-check:** drafter runs `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-721d-agent-authored-appearance-v1.md prompts/ad-721i-dsl-blender-renderer-v1.md` after writing the prompt bodies. (Note: the script takes positional `[string[]]$PromptPaths`, NOT `-DispatchPath`.)
- **Verify-first against HEAD:** every concrete file/line/method citation greps to a hit at HEAD (or the prompt explicitly creates that entity).

---

## 10. AD-numbering verification

**Highest pre-existing AD: 721** (per DECISIONS.md L1565 and decisions-era-4-evolution.md L5170).

| AD | Status |
|---|---|
| AD-721 | SHIPPED (Wave 133, issue #515) |
| AD-721a | Forward marker — Captain avatar editor |
| AD-721b | PROPOSED — phoneme lipsync (issue #529) |
| AD-721c | Forward marker — VR avatars |
| **AD-721d** | **THIS WAVE — issue #531** |
| AD-721e | Forward marker — animation library |
| AD-721f | Forward marker — canvas avatar replacement |
| AD-721g | Forward marker — per-tier baselines |
| AD-721h | Forward marker — VRM upload UI |
| **AD-721i** | **THIS WAVE — issue #537** |
| AD-721j | Forward marker — Computer Use Blender control (issue #537 §Out of scope) |

**Newly reserved sub-AD numbers (filed at gate-3 as forward markers):** AD-721d-1, AD-721i-1, AD-721i-2. No collisions with existing 721a–j ladder.

PROGRESS.md line 11 currently says "current highest AD: AD-698" — that line is stale. **Builder fixes this in-wave** as part of the pre-push checklist (see §8 hard-stop condition #8). Single-line edit, no separate BF.

---

## Final report (Architect)

**Pre-draft validation (mandatory):** Before drafting either prompt body, the architect MUST validate that all `Class.method` and `module.path` references in this dispatch resolve at HEAD. Run `pwsh scripts/phantom-api-precheck.ps1 prompts/WAVE-134-DISPATCH.md` and surface any phantoms in the final report under a dedicated "Phantom-API pre-check" subsection. Zero phantoms is the bar; if any are found, fix the dispatch first, then draft.

Drafter writes both prompts (`prompts/ad-721d-agent-authored-appearance-v1.md`, `prompts/ad-721i-dsl-blender-renderer-v1.md`) only after the Captain approves this dispatch. After both prompts are written, the drafter returns ONE message containing:

1. One-line summary per prompt.
2. Verify-first findings (any contradictions with this dispatch — e.g., `profile_store.py` API shape, `routers/agents.py` endpoint registration site).
3. Risk classification per prompt (LOW / MEDIUM / HIGH).
4. AD-721d: chosen `AvatarDSL` field set + which standing-crew agent (likely Counselor) goes first.
5. AD-721i: confirmed Blender + saturday06 versions targeted; verified `_blender/render_avatar.py` skipped from pytest collection.
6. Forward markers filed (AD-721d-1, AD-721i-1, AD-721i-2).
7. Standing-convention concerns surfaced.
8. Audit trail: file paths actually read; URLs fetched (issue bodies, upstream addon repos).
