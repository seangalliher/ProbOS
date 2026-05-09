# AD-721d — Agent-authored avatar appearance pipeline (v1)

**Wave:** 134
**Depends on:** AD-721 (SHIPPED Wave 133, issue #515)
**Pairs with:** AD-721i (renderer; same wave, builds after `d`)
**Issue:** [#531](https://github.com/seangalliher/ProbOS/issues/531)
**Risk:** MEDIUM (cross-layer: schema + LLM proposal + persistence + UI + endpoints)
**Estimated tests:** ≥ 18 Python + 2 Vitest

> **Builder:** read `prompts/WAVE-134-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

The agent reflects on its personality, standing orders, and recent trust history, then **proposes** an `AvatarDSL` artifact (structured YAML/JSON — *data, not code*). The Captain reviews and approves the DSL through the existing avatar popout. Approved DSL persists on `AppearanceProfile.dsl`. The renderer (AD-721i) consumes the DSL out-of-band and produces a `.vrm`; if the renderer is absent, the DSL is preserved and `CrewVRM` falls back to parametric until an operator runs the renderer.

This AD owns the **runtime + UI + persistence side**. AD-721i owns the renderer side. AD-721d's tests **mock** the renderer and must pass on a machine without Blender.

## 2. Why now

- Wave 133 closed AD-721 (3D crew avatars). Counselor (Echo) is the v1 design partner — she currently lives off either an operator-supplied `Ezri.vrm` or the parametric capsule fallback.
- The Counselor's role in the standing crew is *design partner* — she should be the first crew member to design her own avatar end-to-end as a smoke test of this AD.
- AD-718a (agent-authored voice profile, Wave 136) needs a sibling pattern to mirror; this AD establishes that pattern first.
- Cluster-A roadmap target: every standing-crew agent should have an authored visual identity by the end of the next two waves; this AD unlocks self-service authoring.

## 3. Verified Against Codebase (2026-05-09)

```
grep -n "class AppearanceProfile" src/probos/crew_profile.py
  129: class AppearanceProfile:
  139:     vrm_url: str = ""
  140:     expression_overrides: dict[str, float] = field(default_factory=dict)
  141:     color_palette_hint: str = ""

grep -n "class ProfileStore" src/probos/crew_profile.py
  287: class ProfileStore:
        # NOTE: persistence is JSON-blob via crew_profiles.data TEXT column
        # (sqlite3.connect, NOT aiosqlite). Adding fields to AppearanceProfile
        # auto-round-trips. No new table, no new aiosqlite path.

grep -n "class AvatarsConfig" src/probos/config.py
  922: class AvatarsConfig(BaseModel):
  926:     avatars_dir: str = "data/avatars"
  927:     max_vrm_size_bytes: int = 25 * 1024 * 1024
  928:     fallback_to_parametric_on_error: bool = True

grep -n "_resolve_avatars_dir\|_platform_data_dir" src/probos/routers/system.py
  641: def _resolve_avatars_dir(configured: str) -> Path:
        # BF #539 path-traversal-safe; reused for DSL drafts dir.

grep -n "voice-profile" src/probos/routers/agents.py
  194: @router.put("/{agent_id}/voice-profile")
        # AD-718 placement; appearance endpoints mirror this site.

grep -n "@router\.(get|put|post)" src/probos/routers/agents.py
  40:  @router.get("/{agent_id}/profile")    # AD-721: appearance read site
  178: @router.put("/{agent_id}/proactive-cooldown")
  194: @router.put("/{agent_id}/voice-profile")
  230: @router.post("/{agent_id}/chat")

grep -n "testpaths" pyproject.toml
  93: testpaths = ["tests"]    # constrains pytest collection to tests/ only.
```

> **Dispatch correction:** `WAVE-134-DISPATCH.md` §4 D4 cited `src/probos/profile_store.py` — that file does NOT exist. `ProfileStore` lives in `src/probos/crew_profile.py:287`. Round-trip persistence is via the existing JSON-blob column; adding `dsl` to `AppearanceProfile` is sufficient.

## 4. Scope (v1 only)

D1–D11 below. Renderer interactions are mocked.

## 5. Non-goals (deferred forward markers)

- **AD-721d-1** — Rendered-draft preview surface in HXI before approval (~3 React components + WebSocket plumbing).
- **AD-721a** — Captain Edit Avatar UI (edits DSL directly). Already filed.
- **AD-721b** — Phoneme-driven mouth shapes inside the DSL. Already promoted; runtime visemes flow through that pipeline. The DSL's `expression_resting` is rest-state only.
- **AD-721i** — The renderer itself (paired AD; this prompt mocks it).

## 6. Deliverables

### D1 — `AvatarDSL` Pydantic model

**New file:** `src/probos/avatars/__init__.py` (empty package init).
**New file:** `src/probos/avatars/dsl.py`.

Pydantic v2 model. Every field has a default — `AvatarDSL()` with no args MUST succeed.

Required fields and constraints:

| Field | Type | Constraint |
|---|---|---|
| `body.type` | `Literal["slim","average","stocky"]` | default `"average"` |
| `body.height_cm` | `int` | `field_validator` 140 ≤ x ≤ 210, default 170 |
| `hair.style` | `Literal["short","medium","long","ponytail","bun","shaved"]` | default `"medium"` |
| `hair.color_hsl` | `tuple[int,int,int]` | H 0–360, S 0–100, L 0–100; default `(30, 40, 30)` |
| `face.warmth` | `float` | 0.0 ≤ x ≤ 1.0; default 0.5 |
| `face.jaw` | `Literal["soft","neutral","strong"]` | default `"neutral"` |
| `face.eyes` | `Literal["round","almond","narrow"]` | default `"almond"` |
| `outfit.style` | `Literal["uniform","casual","formal","robe","tactical"]` | default `"uniform"` |
| `outfit.primary_color` | `str` (CSS hex) | regex `^#[0-9a-fA-F]{6}$`; default `"#2a4a6a"` |
| `outfit.accents` | `list[str]` (CSS hex) | each matches regex; default `[]`; max 4 entries |
| `expression_resting` | `Literal["neutral","gentle_smile","focused","alert"]` | default `"neutral"` |
| `notes` | `str` | max length 280 chars; default `""` |

Substructures (`body`, `hair`, `face`, `outfit`) are nested Pydantic models with their own defaults so the top-level default-construction path works.

**Forbidden:** any `exec`, `eval`, `compile`, or `importlib.import_module` call anywhere in this module. Reviewer greps the diff.

### D2 — `AppearanceProfile.dsl` field

**Modify:** `src/probos/crew_profile.py` (extend the `AppearanceProfile` dataclass at line 129–153).

```
===SEARCH===
@dataclass
class AppearanceProfile:
    # ... existing docstring ...
    vrm_url: str = ""
    expression_overrides: dict[str, float] = field(default_factory=dict)
    color_palette_hint: str = ""
===REPLACE===
@dataclass
class AppearanceProfile:
    # ... existing docstring ... (preserve verbatim)
    vrm_url: str = ""
    expression_overrides: dict[str, float] = field(default_factory=dict)
    color_palette_hint: str = ""
    # AD-721d: agent-authored DSL artifact (Pydantic model serialised as dict).
    # `None` = agent has not proposed yet OR Captain has not approved.
    # Round-trips through ProfileStore's JSON-blob column unchanged.
    dsl: dict | None = None
===END REPLACE===
```

> **Storage shape:** persist the **dict form** (`dsl.model_dump()`) on `AppearanceProfile.dsl`, not the Pydantic instance. Re-validate on read with `AvatarDSL.model_validate(profile.appearance.dsl)` whenever a typed object is needed. This keeps `to_dict`/`from_dict` symmetric and avoids accidental Pydantic coupling on `AppearanceProfile`.

Extend `to_dict` and `from_dict` symmetrically (preserve existing `vrm_url` / `expression_overrides` / `color_palette_hint` handling; emit `dsl` only when not `None`).

### D3 — `propose_appearance()` capability on `CognitiveAgent`

**Modify:** `src/probos/cognitive/cognitive_agent.py`.

Add an async method:

```python
async def propose_appearance(self) -> AvatarDSL:
    """Reflect on personality + standing orders + recent trust history,
    return a validated AvatarDSL (NOT yet persisted; Captain must approve).

    Raises:
        AppearanceProposalError: LLM call failed, response oversized,
            or schema validation rejected the proposal.
    """
```

Implementation rules:

1. **Prompt construction.** Pull personality (from the agent's instructions/system-prompt), standing orders (`config/standing_orders/<agent_id>.yaml` if present), and recent trust history (last N=5 deltas from the existing trust network). Pass them to the agent's configured LLM tier (default: standard tier via `LLMClient`).
2. **Strict JSON output mode.** The system prompt MUST request **strict structured output**. Where the LLM tier exposes a `response_format={"type":"json_object"}` parameter (Anthropic / OpenAI-compatible endpoints), use it. Where it does not, the prompt MUST include a hardened example showing the *exact* JSON shape and instruct the model to emit *only* that JSON — no prose, no Markdown fences.
3. **Hardened parse path.** Take the LLM response. Hard-cap size at 16 KiB before any parser sees it. Reject any response containing YAML anchors (`&`) or aliases (`*`) at the byte level. Then `yaml.safe_load(response_text)` (which also handles JSON since JSON is a YAML subset and `safe_load` blocks tag execution). Then `AvatarDSL.model_validate(...)`. Any size-cap miss, anchor/alias hit, parse error, or schema violation → raise `AppearanceProposalError` with the structured reason. **No `compile`/`exec`/`eval`/`importlib.import_module` anywhere in this path.**
4. **Depth guard.** After `yaml.safe_load`, walk the resulting Python object and reject documents whose nesting exceeds 8 levels. Defense-in-depth against parser-resource attacks.
5. **No persistence in this method.** Caller (the endpoint in D7) decides whether to persist after Captain approval.
6. **Logging.** Tier-2 log-and-degrade only on the LLM-call layer; schema violations propagate (`AppearanceProposalError` is raised, not swallowed).

`AppearanceProposalError` is a new exception class defined in `src/probos/avatars/dsl.py`.

### D4 — DSL persistence

**Modify:** `src/probos/crew_profile.py` only (no new file).

Already covered by D2: adding `dsl` to `AppearanceProfile` round-trips through `ProfileStore.update(profile)` automatically because `crew_profiles.data` is a JSON blob (verified at line 287). No new SQLite table. No new `aiosqlite` path. **No `ProfileStore` change beyond what `AppearanceProfile.from_dict` already requires.**

Round-trip test required (in D10).

### D5 — "Design avatar" UI affordance

**Modify:** `ui/src/components/profile/AgentProfilePanel.tsx`.

Add a "Design avatar" affordance:

- Inline SVG icon, `strokeWidth: 1.5`, `strokeLinecap: round`, no fill.
- Inactive: `#666680`. Hover/active: `#f0b060` with `drop-shadow(0 0 4px rgba(240,176,96,0.6))`.
- **No emoji.** Reviewer greps the diff for emoji codepoints (U+1F000–U+1FFFF, U+2600–U+27BF) and fails the prompt on any hit.
- On click: `POST /agents/{agent_id}/appearance/propose` (D7). On 200, render the returned DSL inside the existing avatar popout for Captain review.

### D6 — Captain approval surface

**Modify:** `ui/src/components/profile/CrewAvatarPopout.tsx`.

Add an approval bar inside the existing modal:

- **Approve** — `PUT /agents/{agent_id}/appearance` with the proposed DSL. On 200, persist locally + close modal.
- **Request revisions** — re-call `propose_appearance` with an optional Captain note (string up to 280 chars) appended to the LLM prompt context.
- **Reject** — close modal without persisting.

All three actions are stroke-based SVG buttons. No emoji. No third-party icon library imports.

### D7 — HXI endpoints

**Modify:** `src/probos/routers/agents.py` — both new endpoints registered next to the AD-718 voice-profile endpoint at line 194 (mirror its decorator placement and feature-gate pattern).

```
@router.post("/{agent_id}/appearance/propose")  # returns proposed DSL (not persisted)
@router.put("/{agent_id}/appearance")           # persists DSL after Captain approval
```

- Both are feature-gated on `cfg.avatars.enabled` (return `503` with structured reason when disabled).
- The mounted router prefix is owned by the FastAPI app — decorator paths stay relative (`/{agent_id}/...`), matching every other route in `agents.py`.
- Request/response schemas live in `src/probos/api_models.py` (mirror the AD-718 `SetVoiceProfileRequest` shape — `SetAppearanceRequest`, `ProposeAppearanceResponse`).
- The `PUT` endpoint validates the incoming DSL with `AvatarDSL.model_validate(...)` BEFORE writing. Invalid → `422`.

### D8 — Renderer-cache awareness on the read path

**Modify:** `src/probos/routers/agents.py` (the existing `GET /{agent_id}/profile` at line 40).

Inside the `appearance` field assembly:

- If `appearance.vrm_url` is non-empty, return as-is (existing behavior, unchanged).
- If `appearance.vrm_url` is empty AND `appearance.dsl` is not `None` AND a file exists at `<_resolve_avatars_dir(cfg.avatars.avatars_dir)>/<agent_id>.vrm`, synthesise `vrm_url=<agent_id>.vrm` so `CrewVRM` picks up the rendered cache.
- Otherwise leave `vrm_url` empty → parametric fallback (existing behavior).

**No new endpoint. No file write. Pure read-path synthesis.**

### D9 — Multi-mesh face-split regression test (Vitest)

**New file:** `ui/src/__tests__/CrewVRM.expressionResting.test.tsx`.

Direct regression of AD-721 BF de4107b. Fixture: a VRM with **3 face meshes** carrying overlapping `Fcl_MTH_*` morphs. Assertion: when `appearance.dsl.expression_resting === "gentle_smile"`, all 3 mesh `morphTargetInfluences` indices update — not just the first. Use the existing AD-721 VRM-test scaffolding for the fixture builder.

This test is mandatory. Hard-stop on failure (see §8).

### D10 — Tests (Python)

Three new test files. Boundary cases for every public method (happy + error + edge).

**`tests/test_ad721d_avatar_dsl.py`** (≥ 7 tests):

- `test_default_construction_succeeds` — `AvatarDSL()` returns a valid instance.
- `test_height_cm_lower_bound_rejected` — height_cm=139 → ValidationError.
- `test_height_cm_upper_bound_rejected` — height_cm=211 → ValidationError.
- `test_outfit_color_regex_rejects_non_hex` — `primary_color="red"` → ValidationError.
- `test_outfit_accents_max_4` — 5 accents → ValidationError.
- `test_notes_length_bound` — 281-char notes → ValidationError.
- `test_round_trip_dict` — `AvatarDSL.model_validate(dsl.model_dump())` is identity.

**`tests/test_ad721d_propose_appearance.py`** (≥ 7 tests):

- Mocks `LLMClient.complete` (or whatever the agent's tier uses).
- `test_happy_path_returns_validated_dsl` — well-formed JSON → `AvatarDSL` instance.
- `test_oversized_response_raises` — LLM returns 17 KiB → `AppearanceProposalError`.
- `test_yaml_anchor_rejected` — response contains `&` → `AppearanceProposalError`.
- `test_yaml_alias_rejected` — response contains `*name` → `AppearanceProposalError`.
- `test_deep_nesting_rejected` — 9-level nested dict → `AppearanceProposalError`.
- `test_schema_violation_propagates` — body.type="alien" → `AppearanceProposalError`.
- `test_no_eval_or_exec_in_module` — AST scan of `cognitive_agent.py` AND `avatars/dsl.py` produces zero `Call` nodes whose function id is `eval`/`exec`/`compile`. (Defense in depth — protects against a future regression.)

**`tests/test_ad721d_endpoints.py`** (≥ 4 tests):

- `test_propose_endpoint_returns_dsl` — happy path, mocked agent.
- `test_put_appearance_validates_dsl` — invalid DSL → 422.
- `test_endpoints_503_when_avatars_disabled` — `cfg.avatars.enabled=False` → 503.
- `test_round_trip_through_profile_store` — propose → approve → re-fetch profile → DSL persists.

### D11 — Tests (UI / Vitest)

**`ui/src/__tests__/AgentProfilePanel.designAvatar.test.tsx`** (≥ 2 tests):

- Click "Design avatar" → calls `POST /appearance/propose`.
- Approve in popout → calls `PUT /appearance` with the proposed DSL body.

Plus the regression test from D9.

## 7. Counselor-as-design-partner smoke-test note

After the Builder's gate is green, the Captain's **first end-to-end exercise** of this AD should be Counselor (Echo) proposing her own DSL, reviewing in the popout, approving, and observing the persisted DSL on her profile. This is a manual smoke-test, **not** a code deliverable. The Builder records its outcome in the build report.

## 8. Hard-stop conditions (verbatim from `WAVE-134-DISPATCH.md` §8)

1. **Phantom DSL field.** If AD-721d's tests reference an `AvatarDSL` field that the model doesn't actually define, STOP — do not silently add the field.
2. **Subprocess discipline regression.** Any `subprocess.run` introduced under `src/probos/avatars/` is a hard stop. `asyncio.create_subprocess_exec` only.
3. **`exec`/`eval`/`compile` on DSL content.** Hard stop. Reviewer greps the diff and fails the prompt.
4. **Working-tree integrity.** Pre-flight `git diff --numstat` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to the Captain.
5. **Multi-mesh face-split regression.** D9's Vitest fails → STOP. This is the exact AD-721 BF de4107b shape and we will not regress it.
6. **`bpy` imported at top level outside `_blender/`.** Hard stop.
7. **Operator-supplied 3D assets accidentally committed.** Reviewer audits the diff for any `.vrm`, `.blend`, `.fbx`, `.glb` file. Files under those names ship only `.gitkeep`.
8. **PROGRESS.md stale "current highest AD" line.** Pre-push: Builder MUST update `PROGRESS.md` line 13 (or wherever the live `current highest AD: AD-698` string lives — grep if displaced) to `current highest AD: AD-721i`. Single-line edit, folded into this wave's commit chain.

## 9. Forward markers

- **AD-721d-1** — rendered-draft preview surface in HXI before approval (~3 React components + WebSocket plumbing). File at gate-3 per `BUILDER-EXECUTION-PLAN.md` Post-Sweep step 6.

## 10. What this AD does NOT change

- `ProfileStore` schema (no new SQLite table).
- The AD-721 `CrewVRM` runtime expression layer (no morph-binding changes).
- `AvatarsConfig` (config additions live in AD-721i's prompt — `dsl_drafts_dir` is a renderer-side concern).
- Any third-party 3D asset shipped in-repo (zero assets ship; operator supplies).
- The AD-718 voice-profile endpoint (only mirrors its placement pattern).

## 11. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specific checkpoints (Builder confirms each in the build report):

- Cloud-Ready Storage — DSL flows through existing JSON-blob column; no new `aiosqlite` path.
- Defense in Depth — size cap → anchor/alias reject → safe_load → depth guard → Pydantic validate.
- Three-tier exceptions — LLM-layer Tier-2 (log-and-degrade); schema violations propagate.
- Async discipline — `propose_appearance` is `async`; LLM call uses the existing async client; no fire-and-forget.
- No private-attr access — all extension via public dataclass + Pydantic models.
- Type annotations — all new public methods fully typed.
- Logging quality — every log message has what/why/what-next context.
- HXI Design Principles — stroke SVG, no emoji, amber-active.

## 12. Acceptance criteria

- All ≥ 18 Python tests + 2 Vitest tests pass.
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` green; `cd ui && npx vitest run` green.
- Files touched (target list):
  - **New:** `src/probos/avatars/__init__.py`, `src/probos/avatars/dsl.py`, `tests/test_ad721d_avatar_dsl.py`, `tests/test_ad721d_propose_appearance.py`, `tests/test_ad721d_endpoints.py`, `ui/src/__tests__/CrewVRM.expressionResting.test.tsx`, `ui/src/__tests__/AgentProfilePanel.designAvatar.test.tsx`.
  - **Modified:** `src/probos/crew_profile.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/routers/agents.py`, `src/probos/api_models.py`, `ui/src/components/profile/AgentProfilePanel.tsx`, `ui/src/components/profile/CrewAvatarPopout.tsx`, `ui/src/store/types.ts`, `PROGRESS.md` (single-line `current highest AD` update).
- GH issue [#531](https://github.com/seangalliher/ProbOS/issues/531) closed with a one-line commit reference.
- Forward marker AD-721d-1 filed at gate-3.
- Counselor smoke-test outcome recorded in the build report.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
