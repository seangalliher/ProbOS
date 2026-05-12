# AD-720d-3 — Episodic write for /api/chat vision-routed turns (Wave 154)

**GH:** [#565](https://github.com/seangalliher/ProbOS/issues/565). **Status:** Buildable.

## Problem

`/api/chat` (main composer) vision path at [src/probos/routers/chat.py](src/probos/routers/chat.py) lines ~285–365 returns the vision-tier LLM response directly without storing an episode. This violates Design Principle #8 (every execution path stores an episode) and breaks AD-485 "every interaction stored." The `/api/agent/{id}/chat` path already does this correctly via AD-430b at routers/agents.py:1180–1214.

## Scope

1. After the successful vision-tier `runtime.llm_client.complete(...)` call inside the `if image_ids:` branch in `routers/chat.py` (currently returns at the `return {"response": llm_response.content or "(no response)", ...}` line ~362), store an episode that captures the turn. **Note:** the standard NL path at [chat.py:209-240](src/probos/routers/chat.py#L209) already writes an episode; the vision branch's `return` at ~362 short-circuits that write. The new episode-store block must appear inside the vision branch immediately BEFORE that return.
2. Use `Episode(...)` from `probos.types` with shape mirroring AD-430b but with `anchors.channel="captain_chat"` (NOT `"dm"`; this is the main composer, not a per-agent DM).
3. `agent_ids=["captain"]` — fixed string. The `/api/chat` path has no `agent` object in scope (only `req`); the responding identity on this path is the LLM, not a sovereign agent. Do NOT call `resolve_sovereign_id` here.
4. Tier-2 log-and-degrade: episode write failure must NOT block the response. Wrap in `try / except Exception: logger.debug(..., exc_info=True)`.
5. `outcomes[0]` must include `has_image_attachment=True`, `image_count=len(image_ids)`, `attachment_ids=list(req.attachment_ids)`, `llm_tier=tier`, `llm_model=llm_response.model`.

## Files

- `src/probos/routers/chat.py` — insert episode-write block AFTER `llm_response = await runtime.llm_client.complete(...)` and BEFORE the `return` (~line 360).
- `tests/test_ad720d3_vision_episode_write.py` (new) — 3 tests.

## Tests (≥3)

1. `test_vision_path_writes_episode_on_success` — patch `runtime.llm_client.complete` to return a stub LLMResponse, send a `/api/chat` POST with attachment_ids containing an image (use the AD-734 in-memory PNG fixture pattern), assert `episodic_memory.store` was called once with an `Episode` whose `outcomes[0]["has_image_attachment"] is True` and `anchors.channel == "captain_chat"`.
2. `test_vision_path_does_not_block_on_episode_failure` — make `episodic_memory.store` raise, assert the HTTP response still returns 200 with the LLM content (degrade is silent).
3. `test_vision_path_episode_omitted_when_episodic_memory_unavailable` — `hasattr(runtime, 'episodic_memory')` is False; no exception; HTTP response still returns content.

## Out of scope

- Touching the text-fallback path (already routes through standard decomposer which already stores episodes).
- Sovereign-id resolution for the captain identity (use whatever AD-430b uses — do not invent).
- Per-agent vision (that is AD-720d-2).

## Acceptance

- Full test gate green. New tests pass under `pytest tests/test_ad720d3_vision_episode_write.py -v -n 0`.
- AD-734 pre-commit hook passes (vision shape unchanged).
- Engineering Principles compliance per `.github/copilot-instructions.md`.
- DECISIONS.md gets an AD-720d-3 entry under era-5 progress; PROGRESS.md highest-AD pointer untouched (sub-AD, not a new top-level).

## Commit

`AD-720d-3: episodic write for /api/chat vision-routed turns (Wave 154). Closes #565.`
