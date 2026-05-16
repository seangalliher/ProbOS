# Wave 164 Dispatch — AD-728c Agent-Initiated Render Self-Check

**Wave size:** 1 AD (single-AD wave).
**Highest AD before Wave 164:** AD-738 (per `PROGRESS.md:10`). AD-728c is a sub-AD of AD-728 and does NOT consume a new top-level AD number.

## Theme

Close the agent-perception gap surfaced by Counselor during a live conversation: *"I get telemetry, not perception. I have no way to know if what's rendering on your end actually matches those parameters."*

Captain authorized: *"Like a person looking in a mirror — they don't do it constantly. Configurable rate limits. An agent actively communicating with a human may want to check before the interaction and periodically during the conversation."*

AD-728c flips the `agent_initiated_stub` trigger in `verify_render_coherence` from hard-reject to a gated, two-budget rate-limited path, with results folded into the agent's own working memory.

## Files written (2)

| # | File | Closes | Tests | Build group |
|---|---|---|---|---|
| 1 | `prompts/ad-728c-agent-initiated-render-self-check.md` | AD-728c gh issue (filed Wave 163 closeout) | 12 pytest | A |
| 2 | `prompts/WAVE-164-DISPATCH.md` | (this file) | — | — |

**Estimated test count:** ≈12 pytest. Zero Vitest (no UI surface — explicit out-of-scope per prompt Section "What this does NOT change").

## Build order

```
Build group A:
  A1: AD-728c
```

Single AD. No parallel dispatch.

## Pre-flight checklist

Before drafting per-AD code, Builder MUST:

1. Confirm clean working tree: `git status` → no untracked tracked-file modifications. The 2026-05-08 working-tree-integrity lesson is non-negotiable.
2. Run the full parallel gate: `pytest tests/ -q -n 4 --dist=loadfile` → all green (Wave 163 baseline = 13715 pytest per session memory; confirm at HEAD).
3. UI gate not required for Wave 164 (no UI changes — AD-728c is server-side only). Skipping `cd ui ; npm run build` is approved by the prompt.
4. Read `prompts/ad-728c-agent-initiated-render-self-check.md` fully — including all four phantom checks in the "Verified Against Codebase" footer.
5. For each verify-first claim in the prompt, re-run the indicated grep BEFORE drafting code. Phantom-API protection. Particular attention to:
   - `render_verification.py:115-117` (the trigger block being flipped).
   - `config.py:1107-1123` (the field insertion point).
   - `cognitive_agent.py:3090` / `cognitive_agent.py:3115` (the AD-722 active-conversation signal).
   - `agent_working_memory.py:404` (the `record_observation` ingress).
   - `cognitive_agent.py:246-` (the SENSORIUM_REGISTRY rationale — confirm it is class-level static dispatch, NOT a runtime mailbox).

## Standing rules embedded in the prompt

The Wave 164 standing block (already woven into the AD-728c prompt Section 8):

- **BF-274**: single `replace_string_in_file` for adjacent edits.
- **BF-280**: NO `asyncio.create_subprocess_*` in runtime paths.
- **BF-282**: NO binary stdout capture on Windows.
- **BF-286**: test scaffolding mirrors production event-loop shape.
- **BF-287**: use public registry API (`registry.get(agent_id)`), NOT `registry.agents`. Real `AgentRegistry`-shape fixtures in tests, NOT MagicMock at the substrate boundary. **Reinforced**: the `last_reply_emitted_at` lookup goes through `runtime.registry.get(agent_id)` — the `_FakeRuntime.registry` shim MUST expose `.get(...)` as a real method, not a MagicMock auto-attribute.
- **AD-731 invariant**: image bytes flow through `AttachmentStore` SHA-256 refs. AD-728c reuses `verify_render_coherence` unchanged on this axis — verified by Test 10 source-scan.
- **AD-722c-3**: forward markers use TECHNICAL triggers, NOT calendar dates.
- **AD-738b**: UI gate NOT applicable to Wave 164 (no UI surface).
- **Real Pydantic config fixtures** in tests, NOT MagicMock at the config boundary. BF-287 retrospective.

## Per-commit gate

For the single AD-728c commit:

1. `pytest tests/test_ad728c_render_self_check.py -v -n 0` → ≥12 passing.
2. `pytest tests/test_ad728_render_verification.py -v -n 0` → existing 15 still passing (one test — `test_agent_initiated_stub_hard_rejected` — is updated in this commit; document the update in the commit message).
3. `pytest tests/ -q -n 4 --dist=loadfile` → full parallel gate green.
4. Source-scan invariants:
   - `grep -n 'b64encode\|base64.b64' src/probos/avatars/render_verification.py` → empty (AD-731).
   - `grep -n 'trust_network\|hebbian' src/probos/avatars/render_verification.py` → empty (AD-727 rule #1).
5. Zero new pip / npm dependencies (confirm via `git diff pyproject.toml ui/package.json` empty).

## Hard-stop conditions

Surface to Architect immediately if any of these are hit:

1. The AD-728 captain-command projection helper (resolves `digital_state_summary` + `backend_render_ref`) is NOT module-level shareable from `CognitiveAgent.check_own_render`. Prompt Section 4 phantom-check 4 flags this — Builder either promotes the helper to a module-level function in `avatars/` OR extracts a thin shared helper. If neither path is mechanical (>15 lines of refactor), STOP and surface.
2. `cfg.avatars` does not accept the four new fields under real `SystemConfig()` (e.g. Pydantic v2 frozen-class behavior preventing extension). Verify-first against `config.py:1107-1132` says siblings of existing fields work; if not, STOP.
3. `verify_render_coherence` cannot be augmented for the `agent_initiated_stub` branch without duplicating the vision-LLM call. Prompt explicitly requires REUSING the existing callsite — if the branch flow forces duplication, STOP and surface as architectural revision needed.

## Tracking updates (post-commit)

- `PROGRESS.md`: append Wave 164 section ABOVE the Wave 163 block. Single CLOSED entry for AD-728c summarizing the two-budget rate limit, the working-memory ingress, and the event-bus cost-discipline preservation.
- `docs/development/roadmap.md`: add an AD-728c row under the AD-728 family (after AD-728b's forward-marker row). Reference the gh issue URL from Wave 163 closeout.
- `DECISIONS.md`: append AD-728c entry — single paragraph noting (1) trigger flip, (2) two-budget contextual rate limit (hourly vs per-conversation, never additive), (3) working-memory ingress via `AgentWorkingMemory.record_observation` (NOT SensoriumEntry — see prompt Section 4 rationale), (4) event-bus cost discipline preserved.
- Session memory: append Wave 164 entry to `/memories/session/` (the orchestrator decides the file shape).

## License posture

Zero new pip/npm deps. AD-728c is internal — reuses existing vision-tier infrastructure (AD-728 `verify_render_coherence`, AD-722a-1 `VisionLLMRateLimit`, AD-722 `last_reply_emitted_at`, AD-723a-3 sensorium plumbing for context, AD-728 `AttachmentStore` SHA-256 path).
