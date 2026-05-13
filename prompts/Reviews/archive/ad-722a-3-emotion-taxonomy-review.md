# Review: AD-737 — Per-agent custom emotion taxonomy
**Verdict:** ⚠️ Conditional (highest-risk prompt in Wave 156)
**Dataclass + prompt-builder pieces are sound; the divergence-pipeline integration is under-specified and the `fired_rules` rule-name choice silently breaks `compute_divergence` scoring for every custom emotion.**

Reviewer: Architect (Pass 1, 2026-05-13). Prompt file: `prompts/ad-722a-3-emotion-taxonomy.md`.

---

## Required (must fix before building)

1. **`fired.append(f"custom_{intent}")` breaks `compute_divergence` scoring.**
   Section 3b's REPLACE block appends `custom_professional_concern` to `fired_rules` *instead of* the parent's `intent_concerned`. But [`compute_divergence`](src/probos/avatars/divergence_detector.py#L249) computes the applied set as:

   ```python
   applied_set = frozenset(r for r in applied_fired_rules if r.startswith("intent_"))
   ```

   Custom rule names start with `custom_`, not `intent_` — so they are **filtered out**. The expected set for the resolved parent is `{intent_concerned}` (a non-empty frozenset), the applied set after filtering is the **empty** frozenset, and Jaccard = 0.0 → `match_score = 0.0`, `magnitude = 1.0`. Result: **every reply that uses a custom emotion scores as maximum divergence**, even when the agent's intent was perfectly executed. This contradicts Section 6's stated contract ("the math uses the parent").

   Fix options (architect must choose explicitly):
   - **(a) Append BOTH names.** `fired.append(rule["rule_name"]); fired.append(f"custom_{intent}")` so the parent's `intent_concerned` survives the `startswith("intent_")` filter and the custom name remains in the snapshot for observability. Lowest blast radius.
   - **(b) Extend `compute_divergence`'s filter** to accept `custom_*` and resolve via `_resolve_intent_name` when computing the expected set. Larger change; would require resolving the custom name back to its parent inside `compute_divergence` — requires threading `custom_emotions` into the pure function or pre-resolving the name in the caller.
   - **(c) Append the parent rule name ONLY** and rely on the `intent_emotion` field on `DivergenceResult` to carry the agent's custom vocabulary. Simplest; loses the `custom_X` signal in `fired_rules`.

   Recommend option (a) — preserves observability and is one extra line. Test 6 must then assert BOTH names are present.

2. **`apply_divergence_check` integration is unspecified.**
   The true single call site of `parse_intent_self_tag` is [src/probos/avatars/divergence_detector.py:356](src/probos/avatars/divergence_detector.py#L356), inside `apply_divergence_check` — NOT `routers/agents.py` as Section 2c claims. The same helper also calls `apply_voice_modulation(voice_profile, signals, intent=intent)` at [line 378](src/probos/avatars/divergence_detector.py#L378) and then `compute_divergence(intent_emotion=intent, ...)` at line ~384. All three calls need `custom_emotions` threaded:
   - `parse_intent_self_tag(response_text, custom_emotions=…)` — to accept the custom name.
   - `apply_voice_modulation(voice_profile, signals, intent=intent, custom_emotions=…)` — to compose the delta.
   - `compute_divergence` — needs either pre-resolution of `intent` to the parent v1 name OR a new `custom_emotions` kwarg.

   The prompt only provides SEARCH/REPLACE for the `snapshot_for_agent` call site in `telemetry.py` (Section 3c). The `apply_divergence_check` modifications are described in prose ("Builder: grep and find") but never shown as code. The Builder will have to write the most subtle part of this change unaided. Provide explicit SEARCH/REPLACE blocks for `apply_divergence_check`.

3. **Custom-name input is not normalised at parse time.**
   `_TAG_RE` accepts `[a-zA-Z_]+` and the existing `parse_intent_self_tag` calls `.strip().lower()` before looking up. The prompt's `_resolve_intent_name(name, custom_emotions)` does `custom_emotions.get(name)` — but `CrewProfile.__post_init__` validates custom keys against `r"^[a-z][a-z_]{0,29}$"` (lowercase). When the LLM emits `<intent emotion=Professional_Concern>`, `parse_intent_self_tag` lowercases to `professional_concern`, which matches; good. But if a future operator forgets to lowercase the key in their seed file, the validator rejects it — defense-in-depth holds. Confirm this is intentional and add a one-line test asserting the lowercase-only invariant catches `EmotionProfile` keys like `"ProfessionalConcern"`.

## Recommended

1. **`SHIFT_BOUND: ClassVar[float] = 0.15` on a non-frozen dataclass.**
   `EmotionProfile` is not `@dataclass(frozen=True)`. Mixing `ClassVar` with mutable dataclass fields is fine but conventionally `frozen=True` is preferred for value objects like this. Sibling `VoiceProfile` is also non-frozen, so consistency wins — accept as-is but flag.

2. **`from probos.avatars.divergence_detector import EmotionalIntent` inside `__post_init__` is a runtime import.**
   Necessary to break the import cycle (Section 1a explains the reason). But it runs on every `EmotionProfile()` construction, including during `from_dict()` round-trips loaded at startup for every crew member. Cache the imported enum values at module level via a lazy global, or push the validation into a separate helper called once at the `CrewProfile.__post_init__` boundary. Minor perf nit unless thousands of profiles are loaded.

3. **`_CUSTOM_NAME_RE = re.compile(...)` recompiled per `__post_init__` call.**
   Move the regex to module level (outside the `__post_init__` body). Same recompile-per-construct concern as above. One-line fix.

4. **Test 7 fixture complexity.**
   `test_build_intent_self_tag_instruction_includes_custom_names` requires constructing a minimal `CognitiveAgent` plus stubbing `runtime.profile_store` plus `runtime.config.avatar_telemetry.divergence_detection`. The prompt doesn't reference an existing test fixture pattern for `CognitiveAgent` instantiation. Recommend pointing the Builder at `tests/test_ad722a_*.py` for the closest fixture pattern, or build a `_FakeRuntime` stub inline.

5. **`apply_voice_modulation`'s caller in `snapshot_for_agent` (Section 3c).**
   The new line `custom_emotions=crew.custom_emotions if crew else None` is correct, but the prompt doesn't include the SEARCH context for line ~725. Provide a 3-line SEARCH block so the Builder doesn't miss the location.

6. **Missing test for negative interaction with v1 emotion.**
   What happens when an agent declares a custom emotion AND the LLM emits a v1 emotion in the same conversation? Should still work — the custom-emotions lookup short-circuits via `if name in INTENT_EXPECTED_RULES: return name` in `_resolve_intent_name`. Add a test asserting `parse_intent_self_tag("<intent emotion=warm>", custom_emotions={...})` returns `"warm"` (parent path still wins).

7. **No test for `EmotionProfile.from_dict` round-trip.**
   `to_dict()` / `from_dict()` are defined but not tested. Custom emotions persist via `CrewProfile`'s JSON-blob column; a corrupted round-trip would silently downgrade custom palettes to empty. Add a one-line round-trip test.

## Nits

1. **"max 8 custom emotions" rationale is in the prompt but not in the validator error message.** Validator says `"custom_emotions max 8 entries, got N"` — fine. Add the rationale to the dataclass docstring so future maintainers don't bump it without thinking.

2. **`from probos.crew_profile import EmotionProfile  # noqa: F401  AD-737`** inside `TYPE_CHECKING` of `divergence_detector.py` and `telemetry.py` — fine, but the `AD-737` trailing comment is non-standard for `noqa`. Use a separate comment line if you want the AD trace.

3. **Forward-marker AD-737a (TS-side parity)** is well-described in Section 6 and the Forward markers section. Good.

4. **`logger.debug(...)` for stale `inherits` in `_resolve_intent_name`** — Section 2a. Per copilot-instructions §"Logging Standards", `warning` is the more appropriate level for "a feature is silently degrading because of stale config." The post-validator path means this should be unreachable in practice — DEBUG is acceptable. Borderline.

## Verified

- **`EmotionalIntent` enum has exactly the 8 names** at [divergence_detector.py:33-44](src/probos/avatars/divergence_detector.py#L33): WARM / CONCERNED / EXCITED / APOLOGETIC / FORMAL / PLAYFUL / REASSURING / NEUTRAL ✓
- **`_TAG_RE` already accepts `[a-zA-Z_]+`** at [divergence_detector.py:86-89](src/probos/avatars/divergence_detector.py#L86) — no regex change needed ✓
- **`parse_intent_self_tag` at line 173** with current signature `(text: str) -> str | None` ✓
- **`apply_voice_modulation` at line 396** with current signature `(profile, signals, intent=None) -> ModulationSnapshot` ✓
- **Caller in `snapshot_for_agent` at line 725** ✓ (prompt says 719-727)
- **`_build_intent_self_tag_instruction` at lines 3170-3196** in `cognitive_agent.py` ✓ (prompt says 3175-3196; close)
- **Forward markers** at [telemetry.py:184-188](src/probos/avatars/telemetry.py#L184) and [divergence_detector.py:36-37](src/probos/avatars/divergence_detector.py#L36) confirm this AD's identity ✓
- **`runtime.profile_store`** exists at [src/probos/runtime.py:410](src/probos/runtime.py#L410) — the prompt's profile-store lookup pattern in `_build_intent_self_tag_instruction` is realistic ✓
- **`_REQUIRED_INTENT_EMOTIONS`** at [telemetry.py:97](src/probos/avatars/telemetry.py#L97) is fixed; manifest invariant preserved ✓
- **Layer discipline.** Changes touch `crew_profile.py` (substrate), `avatars/` (cognitive cross-cutting), `cognitive_agent.py` (cognitive). All within the cognitive boundary; no Substrate-imports-Cognitive violations.
- **HXI Design Principle #3.** No UI change in v1; principle not relevant here.
- **AD-731 invariant preserved.** No bus / RPC / attachment changes.
- **Manifest invariant preserved.** No edits to `modulation_manifest.json` or `_REQUIRED_INTENT_EMOTIONS`. The "schema fixed; deviations require an architecture-decision review" rule at [telemetry.py:155-160](src/probos/avatars/telemetry.py#L155) holds.
- **Per-agent palette is genuinely per-agent.** No cross-agent leakage path — `_resolve_intent_name` only reads the caller's `custom_emotions`.
- **Boundary tests adequate in shape** (7 tests cover validator boundaries, parser, modulation, prompt-builder), pending the divergence-scoring fix and the recommended round-trip test.
- **License posture clean.** Apache 2.0, no external absorption, no new deps.

---

## Re-review pass record

_None yet — first pass conditional._

---

### Re-review (pass-2, 2026-05-13)

**Verdict:** ✅ Approved
**All three pass-1 Required findings (R3 scoring corruption, R4 under-specified integration, R5 test gaps) resolved. The dual-tag + pre-resolution fix is mathematically sound and verified end-to-end against the live `compute_divergence` filter.**

#### Required
_None._

#### Recommended
_None new._ (Pass-1 Recommended items 1-7 explicitly deferred or covered per the architect's Revision closing notes.)

#### Nits
_None new._

#### Verified

**R3 — Scoring corruption math verified against HEAD.**
With the dual-tag fix in Section 3b and the pre-resolution fix in Section 2c, end-to-end math holds:

- `apply_voice_modulation(..., intent="professional_concern", custom_emotions={"professional_concern": EmotionProfile(inherits="concerned")})` emits `fired_rules = (..., "intent_concerned", "custom_professional_concern")`.
- `apply_divergence_check` computes `resolved_v1 = _resolve_intent_name("professional_concern", ...) = "concerned"` and passes `intent_emotion="concerned"` to `compute_divergence`.
- Live `compute_divergence` at [src/probos/avatars/divergence_detector.py:241-258](src/probos/avatars/divergence_detector.py#L241-L258) computes:
  - `expected = INTENT_EXPECTED_RULES["concerned"] = frozenset({"intent_concerned"})` (verified [divergence_detector.py:58](src/probos/avatars/divergence_detector.py#L58))
  - `applied_set = frozenset({r for r in fired if r.startswith("intent_")}) = frozenset({"intent_concerned"})` (custom_X stripped by the live `startswith("intent_")` filter at [line 260-262](src/probos/avatars/divergence_detector.py#L260-L262))
  - Jaccard intersection = 1, union = 1 → `match_score = 1.0`, `magnitude = 0.0`.
- Then `dataclasses.replace(result, intent_emotion="professional_concern")` restores the custom name for downstream observability.

This matches the literal-`concerned` reply score exactly. The math passes.

**R4 — `apply_divergence_check` SEARCH/REPLACE byte-accuracy.**
Pass-1 review identified the integration as prose-only. The revised Section 2c provides an explicit SEARCH/REPLACE block. **Verified against [src/probos/avatars/divergence_detector.py:355-388](src/probos/avatars/divergence_detector.py#L355-L388)**: the SEARCH block (`intent = parse_intent_self_tag(response_text)` through the `result = compute_divergence(...)` call ending at line ~388) matches the live file byte-for-byte, including whitespace, comments, and indentation. The REPLACE block correctly threads `custom_emotions` through all three call sites (parse, modulate, score) and applies the `dataclasses.replace` restoration. `_resolve_voice_profile_for_intent` retention is correct.

**R5 — Test 8 `test_custom_emotion_divergence_score_equals_parent` is the canonical assertion.**
Test 8 at line 545 of the prompt asserts:
- `result_custom.match_score == result_parent.match_score`
- `result_custom.signed_divergence == result_parent.signed_divergence`
- `result_custom.magnitude == result_parent.magnitude`
- `result_custom.intent_emotion == "professional_concern"` (custom name surfaced)
- `result_parent.intent_emotion == "concerned"` (v1 name surfaced)

This pins the v2-parity contract end-to-end through `apply_divergence_check`. Critical-rationale comment on test 6 (line 544) also updated to assert BOTH `intent_concerned` AND `custom_professional_concern` in `fired_rules` with explicit failure-mode citation. Test count updated 7 → 8 with optional 9th retained.

**Call-site location correction landed.** Section 2c explicitly notes `parse_intent_self_tag` has one caller and it is in `divergence_detector.py:356`, NOT `routers/agents.py` as pass-1 noted in the original. ✓

**No scope change.** Files-touched list, AD-731 invariant, manifest invariant, `_REQUIRED_INTENT_EMOTIONS` immutability, `EmotionalIntent` enum immutability, and the v1 fixed-8 invariant are all preserved.

**All pass-1 Verified items still hold.** Enum locations, `_TAG_RE`, `apply_voice_modulation` and caller line references, forward markers, `runtime.profile_store` wiring, layer discipline.
