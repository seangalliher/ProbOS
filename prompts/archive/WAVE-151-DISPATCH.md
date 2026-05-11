# Wave 151 Dispatch — AD-730 Vision Pipe-Through for Per-Agent DMs

**GH issue:** [#630](https://github.com/seangalliher/ProbOS/issues/630)
**Spec:** `prompts/ad-730-agent-chat-vision.md`
**Dependencies:** AD-720d (Wave 139, shipped — `/api/chat` vision tier wiring; reused verbatim)
**Estimated tests:** ≥ 10 backend + ≥ 2 Vitest

## One-line summary

Pipe image attachments past the agent prompt boundary. Today `agent_chat` augments the prompt text with `[Captain attached an image (id=...)]` markers; the receiving agent knows an image *exists* but cannot *see* it. This wave threads the Anthropic-shape `vision_messages` array through `IntentMessage.params` so the agent's perception turn routes to the configured vision tier when an image is present.

## What this wave does

When `req.attachment_ids` contains any `image/*` MIME:
1. Build the multimodal messages array via existing `build_multimodal_messages()` (already does the work for `/api/chat`).
2. Verify the configured `attachments.vision_tier` health (operational gate).
3. Plumb the messages array through `IntentMessage.params['vision_messages']` to the receiving agent.
4. Agent's `direct_message` LLM call routes through vision tier with `LLMRequest(messages=...)` when the param is present.
5. Text-only DMs keep the existing path (zero behavior change).

## What this wave does NOT do (forward markers)

- **AD-730-1:** Vision UI attach button in WardRoomThreadDetail (backend already routes — needs UI surface only).
- **AD-730-2:** Multi-image DMs. v1 supports first image only; others get text markers via existing augmentation.
- **AD-730-3:** Agent image generation in DM replies (separate capability AD).
- **AD-730-4:** Federation peer-to-peer vision DMs (inherits AD-480 governance).
- **AD-730-5:** Vision tier override per agent type (e.g. Imaging Officer using a different tier).

## Pre-flight gate

1. `git status` clean; HEAD at `a575209` (Wave 150 BF) or later.
2. `pytest tests/ -q -n 4 --dist=loadfile` — green baseline.
3. `cd ui && npx vitest run` — green baseline.
4. Vision plumbing verified — `build_multimodal_messages` exists at `src/probos/cognitive/vision_dispatch.py:81`; `attachments.vision_tier` is in config.

## Hard-stops

- AD-722a divergence detector regression — adding image bytes to the perception turn must not break the `<intent emotion=...>` parser or alter `applied_fired_rules` baselines.
- Vision tier health probe pattern from `/api/chat` lines 309-325 must be reused as-is (don't re-implement the operational-status check).
- `IntentMessage.params['vision_messages']` is a NEW param; cannot collide with existing keys.

## Commit message format

```
AD-730 (Wave 151): vision pipe-through for per-agent DMs

Closes #630. When an image attachment is included in /api/agent/{id}/chat,
the receiving agent's perception turn now routes through the configured
attachments.vision_tier and sees the actual image bytes (not just the
[Captain attached an image] marker). Text-only DMs unchanged.
```

## Tracking

- `PROGRESS.md` — close #630, update test count.
- `docs/development/roadmap.md` — mark AD-730 shipped, add 5 forward markers.
- `prompts/wave-plan.yaml` — add Wave 151 entry.
- `DECISIONS.md` — closure note under AD-730 (issue body already drafted the decision).
- File AD-730-1 through AD-730-5 as GH issues at retrospective.
