# Wave 158 — Pass 1 Review Summary

**Reviewer:** Architect. **Date:** 2026-05-13. **Captain:** asleep (autonomous review).

## Per-Prompt Verdict

| # | Prompt | Verdict | One-line justification |
|---|---|---|---|
| 1 | AD-737a — divergence_detector hygiene | ✅ Approved | Solid; behavior-equivalence proof is clean; caller audit accurate (2 prod sites both inside `apply_divergence_check`). |
| 2 | AD-738a — orchestrator audit + voice.ts MODE gate | ✅ Approved | PowerShell here-string interpolation correct on inspection; renumber preserves audit history (append-only in DECISIONS.md). |
| 3 | AD-738b — UI gate `npm run build` standing rule | ✅ Approved | Surgical 2-file process change; current text matches verify-first claims byte-for-byte. |
| 4 | AD-738c — rhubarb→Oculus mapping polish | ✅ Approved | Two independent cheap edits, default-kwarg backward-compat preserved, sound rationale. |
| 5 | AD-738e-1 — per-emotion Piper prosody | ⚠️ Conditional | One Required finding (fabricated authorization claim + private-helper import); 3 Recommended; architecturally sound additive feature. |

## Total Findings

| Tier | Count | Distribution |
|---|---|---|
| Required | **1** | All in AD-738e-1 (#5) |
| Recommended | **5** | AD-737a×1, AD-738a×1, AD-738c×1, AD-738e-1×3 (one of which is a duplicate of AD-737a's Recommended #1 — cross-prompt synergy) |
| Nits | ~10 | Distributed evenly; line-number drift, comment quality, helper-naming |

## Highest-Risk Prompt

**AD-738e-1 (Per-emotion Piper prosody)** — Captain flagged this as the high-blast-radius prompt; review confirms. Risk profile:

- **Surface area:** Touches 8 production files across 3 layers (TTSBackend protocol, PiperBackend, two routers, voice.ts, ProfileChatTab.tsx).
- **User-perceived effect:** Per-emotion prosody changes the *character* of every Counselor / agent voice. If override values are wrong, every utterance sounds wrong.
- **Required finding:** Private-helper cross-module import (`_resolve_intent_name`) violates copilot-instructions Open/Closed + Demeter. Fix is small (3-line public alias OR cross-prompt synergy with AD-737a adding `resolved_v1_emotion` field) but must land before build.
- **Mitigation already in prompt:** Additive guarantee — `resolve_prosody_overrides(None) == {}` keeps PiperBackend defaults. Backward compat preserved across the entire blast radius. The "if it goes wrong" recovery is a 1-commit revert of the table values; no migration cost.

## Cross-Prompt Concerns

1. **Forward-marker renumber is the wave's load-bearing dependency.** AD-738a Section 3 renumbers Wave-157's `AD-738a/b/c/d` placeholders → `AD-738f/g/h/i` in DECISIONS.md (append-only) + roadmap.md (in-place with traceability suffix). Prompts 3 and 4 (`AD-738b`, `AD-738c`) reuse the freed slots. Per copilot-instructions hard rule on AD numbering ("never reuse"), renumbering *placeholders that never shipped* is acceptable; the audit history is preserved by appending the renumber clarification rather than rewriting the original forward-marker paragraph. **Build order #2 → #3 → #4 must be strictly respected.**

2. **AD-737a × AD-738e-1 synergy.** AD-737a is already touching `apply_divergence_check` to collapse the double-parse. AD-738e-1 needs the resolved-v1 emotion in `DivergenceResult` (currently stores custom name only). The natural merge: AD-737a adds `resolved_v1_emotion: str | None` to the dataclass; AD-738e-1's Section 6 collapses from 18 lines of nested resolution to ~3 lines of field-read. **Recommended (not Required)** — the two prompts are independently correct, but the merge is cheaper and avoids AD-738e-1's Required finding entirely (no need to import `_resolve_intent_name` if the resolved value is already on the result).

3. **`ui/src/audio/voice.ts` co-edit.** Touched by Prompts 2 (`_resetTtsStatusForTests` at line 143) AND 5 (`speakResponse` at line 167 + POST body at line 209). Non-overlapping line ranges; build in numeric order. Dispatch already notes this.

4. **License hygiene.** All 5 prompts confirmed all-internal. No `pyproject.toml` or `ui/package.json` edits. No external code absorbed. Apache 2.0 compliant. ✓

5. **HXI surface.** Confirmed: AD-738e-1 is audio-only (no new chrome). AD-738c's morph-residual bump is a tuning of existing motion, not new UI. AD-738a's `_resetTtsStatusForTests` is an invisible test affordance. No HXI Design Principle violations. ✓

6. **BF-279 UI gate compliance.** Prompts 2, 4, 5 (UI-touching) all include `npm run build` in their verification commands. AD-738b ships the standing-rule codification. Self-consistent. ✓

7. **Slot-reuse interpretation note.** The Captain's framing ("forward markers were never assigned to ADs that shipped — they were placeholders — so renumbering placeholders is acceptable") is **correct** under the copilot-instructions hard rule. The rule says "never reuse" for AD numbers that have *shipped* (i.e., have a closure block + commit). The Wave-157 AD-738a/b/c/d entries are roadmap reservations, not shipped ADs. Reusing the slots is acceptable provided the audit trail is preserved (append-only DECISIONS.md, in-place roadmap with "renumbered from" suffix). AD-738a Section 3 does both correctly.

## Recommendation

**PROCEED to revision.** Pass-1 verdict: 4 of 5 prompts are ✅ Approved; AD-738e-1 has exactly 1 surgical Required finding that the prompt author can fix in <15 minutes (add a 3-line public alias in `divergence_detector.py` OR add a `resolved_v1_emotion` field via AD-737a synergy). The wave is hygiene-grade per Captain's "Convention #15 relaxed" note; this distribution (1×⚠️ + 4×✅) is well within the relaxed bound.

Pass-2 should verify:
1. AD-738e-1 Required #1 is resolved (public alias OR AD-737a field).
2. AD-738e-1 Recommended #1 (Section 6 boundary test) is addressed.
3. No other prompt has drifted.

After Pass 2 lands, Builder can dispatch. Total estimated wave wall-time still ~7–10h.

---

## Verified Against Codebase (2026-05-13)

```
grep -n "parse_intent_self_tag(" src/probos/avatars/divergence_detector.py
  204: def parse_intent_self_tag(
  392:     intent = parse_intent_self_tag(response_text)
  410:         intent = parse_intent_self_tag(
# → 2 production call sites both inside apply_divergence_check ✓

grep -n "function Format-Gate2\|function Format-BuildDispatch" scripts/wave-orchestrator.ps1
  262: function Format-BuildDispatch {
  327: function Format-Gate2 {

grep -n "## Standing Rules\|License policy" prompts/BUILDER-EXECUTION-PLAN.md
  24: ## Standing Rules (carry forward from prior sweep)
  32: - **License policy (Captain rule, 2026-05-09):** ...

grep -n "_PRESTON_BLAIR_TO_OCULUS\|def _map_preston_blair_to_oculus" src/probos/avatars/rhubarb_backend.py
  41: _PRESTON_BLAIR_TO_OCULUS: dict[str, str] = {
  67: def _map_preston_blair_to_oculus(pb: str) -> str:
  280:                 viseme=_map_preston_blair_to_oculus(value),

grep -n "class EmotionalIntent\|^def _resolve_intent_name\|^def parse_intent_self_tag" src/probos/avatars/divergence_detector.py
  35: class EmotionalIntent(str, Enum):
  94: def _resolve_intent_name(
  204: def parse_intent_self_tag(

grep -n "def select_backend\|async def synthesize" src/probos/audio/tts/*.py
  __init__.py:16: def select_backend(backend_name: str, config: "TTSConfig") -> TTSBackend:
  backends.py:33:     async def synthesize(self, text: str) -> TTSResult | None:
  null_backend.py:18:    async def synthesize(self, text: str) -> TTSResult | None:
  piper_backend.py:88:    async def synthesize(self, text: str) -> TTSResult | None:

grep -n "JSON.stringify({ text })\|export function speakResponse" ui/src/audio/voice.ts
  167: export function speakResponse(
  209:         body: JSON.stringify({ text }),

grep -n "AD-738a\|AD-738b\|AD-738c\|AD-738d" docs/development/roadmap.md
  361-364: forward-marker rows (verified verbatim in AD-738a Section 3a)

grep -n "Forward markers.\*AD-738a" DECISIONS.md
  2446: Forward markers paragraph (verified verbatim in AD-738a Section 3b)
```
