# AD-933 — Wire the one-shot escalation ladder into group chat

**Target repo:** OSS (`d:\ProbOS`)
**Highest committed AD:** AD-932 (`b9353af0`). **This AD = AD-933.**
**Mode:** Builder. Write code, run gates, update trackers. Do NOT make architectural decisions beyond this spec.

---

## Problem (verified against HEAD)

The 1:1 chat path and the group-chat fan-out are **structurally identical** up through the intent
bus send — both build `IntentMessage(intent="direct_message", ...)`, call
`runtime.intent_bus.send(intent)`, and read `result.result`:

- **1:1 path** — `routers/agents.py` `agent_chat`: after `result = await runtime.intent_bus.send(intent)`
  (line ~2216) it constructs a `DmReplyContext` + `DmReplyPipeline` and runs
  `await pipeline.run()` then `pipeline.build_response()` (lines ~2263–2271). The pipeline is the
  **post-LLM escalation + cleanup ladder** (AD-726): inline mesh reads (AD-869), `[ACTION]`
  dispatch (AD-745), `[CREATE_TASK]` (AD-845), artifact extraction (AD-797), notebook (AD-911),
  plus 1:1-specific steps (sanity-gate retry, games, episodic, divergence, emotion, avatar sampling).

- **Group fan-out** — `routers/thread_fanout.py` `group_chat_fanout._send_one`: after the **same**
  `result = await runtime.intent_bus.send(intent)` (line ~305) it takes
  `reply_text = str(result.result) ...` **RAW** (line ~312) and persists it. It **never constructs
  the pipeline.**

**Consequence:** group chat is **Tier-1 only**. An agent in a group chat cannot resolve an inline
mesh read, cannot dispatch a browser `[ACTION]`, and cannot open a task via `[CREATE_TASK]` —
the entire escalation ladder that exists on the 1:1 path is missing in the group path. This blocks
the "ask the room to do something complex → it spins up a task / task room" collaboration flow.

`DmReplyPipeline` was already **extracted** from the endpoint (AD-726) precisely so it can be reused.
The fan-out simply never got wired to it.

---

## Decision — wire an **escalation subset**, not the full pipeline

Running the **full** `run()` verbatim on group replies is **wrong** because several steps carry
1:1 semantics. The decisive one: `step_5_episodic_store` (reply_pipeline.py ~1166) hardcodes
`session_type:"1:1"`, `channel:"dm"`, `participants:["captain", callsign]`. Firing it on a
multi-agent group reply writes **mislabeled** episodes — a learning-loop integrity regression.
`step_6` (working memory) similarly records `"Captain DM"`. `step_2/3` (games), `step_4b`
(outbound DM), `step_7` (divergence), `step_9` (emotion), `step_8` (avatar `exit_dm`) are all
1:1/avatar-scoped.

So AD-933 runs only the **channel-agnostic escalation steps** — each is a strict no-op for any
reply lacking its marker, and the relevant markers are only emitted by specifically-taught agents
(e.g. Yeo for `[CREATE_TASK]`), so the subset is inherently safe and bounded:

| Step | AD | Tier | Why it's safe in group |
|---|---|---|---|
| `step_4e_action_dispatch` | AD-745 | T2 | parses `[ACTION]`; gated on `browser_tool.action_dispatch_enabled`; uses `params.thread_id` |
| `step_4i_notebook_parse` | AD-911 | T2 | parses notebook markers; no-op without them |
| `step_4h_mesh_read_parse` | AD-869 | T2 | read-only mesh intents (allowlist); no-op without a read marker |
| `step_4f_extract_artifacts` | AD-797 | T2 | artifact extraction; no-op without an artifact block |
| `step_4g_create_task_parse` | AD-845 | T3 | **the key one** — `[CREATE_TASK]` → dispatchable work item; no-op without the tag |

Preserve their relative order from `run()`: **4e → 4i → 4h → 4f → 4g**. None of the module's
ordering invariants (sanity-before-games, self-check-before-episodic, divergence-before-emit)
involve these five steps, so the subset is internally order-independent; keep run()-order for
clarity.

**Explicitly EXCLUDED** (1:1 semantics / latency / mislabel risk — each a forward marker if ever
wanted in group): sanity-gate retry (step_1), games (2/3), self-check (4), image-gen (4c),
follow-up (4d), outbound-DM (4b), episodic (5), working-memory (6), divergence (7),
mark-emitted/avatar (8), emotion (9).

---

## Changes

### 1. `src/probos/cognitive/dm/reply_pipeline.py` — add a subset runner (additive, DRY)

Refactor the hardcoded step tuple inside `run()` into a helper so both the full run and the subset
share one source of truth. **`run()` behavior must stay byte-identical** (same steps, same order,
same per-step Tier-2 guard).

- Extract the existing 17-step tuple in `run()` into `def _full_steps(self) -> tuple[Callable, ...]`
  (return the exact same tuple in the exact same order).
- Add `def _escalation_steps(self) -> tuple[Callable, ...]` returning
  `(self.step_4e_action_dispatch, self.step_4i_notebook_parse, self.step_4h_mesh_read_parse,
  self.step_4f_extract_artifacts, self.step_4g_create_task_parse)`.
- Extract the `for step in (...)` body into `async def _run_steps(self, steps) -> None` (the
  existing per-step `try/except … logger.warning("AD-726: pipeline step %s raised …")` guard,
  verbatim).
- `run()` becomes `await self._run_steps(self._full_steps())`.
- Add public `async def run_escalation_only(self) -> None:` →
  `await self._run_steps(self._escalation_steps())`. Docstring: AD-933, the channel-agnostic
  escalation subset reused by the group fan-out; lists the five steps + why the rest are excluded.

No change to any step method. No change to `DmReplyContext`. No change to `build_response()`.

### 2. `src/probos/routers/thread_fanout.py` — run the subset in the fan-out

In `group_chat_fanout`, resolve the sanity gate **once** before the `asyncio.gather` (DRY; step_4g
needs it): `sanity_gate = getattr(runtime, "dm_sanity_gate", None)`.

In `_send_one`, **after** `result = await runtime.intent_bus.send(intent)` and computing the raw
`reply_text`, and **only when a real reply came back** (`result and result.result`), construct the
context + pipeline and run the subset, then use the (possibly mutated) text:

```python
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline  # top-of-module import

# … inside _send_one, after reply_text is computed from result.result …
if result and result.result:
    try:
        pipeline = DmReplyPipeline(DmReplyContext(
            runtime=runtime,
            agent=agent,                     # already resolved above for callsign/vision
            agent_id=agent_id,
            callsign=callsign,
            req_message=captain_body,
            response_text=reply_text,
            has_image_attachment=bool(vision_messages),
            per_attachment=[],
            sanity_gate=sanity_gate,         # resolved once before gather
            params=params,
            message_text=captain_body,
            sampling_state=None,             # no avatar bracket in group context
            avatar_event_bus=None,
            chat_thread_id=thread_id,
        ))
        await pipeline.run_escalation_only()
        reply_text = pipeline.ctx.response_text or reply_text
    except Exception:
        logger.warning(
            "AD-933: escalation subset failed for thread=%s agent=%s; "
            "shipping raw reply", thread_id, agent_id, exc_info=True,
        )
```

Then persist `reply_text` (the existing `store.append_message(...)`) and return it as before. The
`reply_text` is now tag-stripped + may carry the `(Task opened: <id>)` suffix from step_4g.

Notes:
- `agent` is already resolved at the top of `_send_one` (for callsign/vision) — reuse it; if it's
  `None`, skip the pipeline (no agent → can't escalate).
- Keep the whole block Tier-2 (the inner `try` + the per-step guards inside the pipeline) so a
  failure never silences a reply — degrade to the raw `reply_text`.
- Do NOT change the facilitator, the `IntentMessage`, the vision handling, or the persist call.

---

## Tests — `tests/test_ad933_group_chat_escalation.py` (BF-287: real fixtures, no MagicMock at the substrate boundary)

Use a real `ChatThreadStore` (tmp), a real `IntentBus(SignalManager(reap_interval=1.0))`, a
real-but-fake registry/agent that returns a canned reply via a subscribed `direct_message` handler,
a real `WorkItemStore` (tmp) on `runtime.work_item_store`, and the **real** `dm_sanity_gate`
(`runtime.dm_sanity_gate`). Mirror the AD-914/AD-915/AD-924 harness shape already in the repo.

Floor **+8**:
1. **CREATE_TASK escalates in group** — the dispatched agent's canned reply contains
   `[CREATE_TASK title="X" | instructions="Y" | specialist=@bones]`; assert a work item is created
   in the real `WorkItemStore` (dispatchable, `tags=["yeo-delegated"]`) AND the persisted thread
   reply has the tag stripped + `(Task opened: <id>)` suffix.
2. **Plain reply is a no-op** — a reply with no markers persists unchanged; zero work items.
3. **`dm_sanity_gate is None` honest-degrades** — CREATE_TASK tag present but
   `runtime.dm_sanity_gate=None`; reply ships (tag may remain), no crash, no work item.
4. **No 1:1 episode is written from the group path** — wire a real/recording `episodic_memory`;
   assert `store` is NOT called with a `session_type:"1:1"` episode by the fan-out (proves step_5
   is excluded).
5. **mesh-read marker** — a reply with an AD-869 read marker resolves inline or honest-degrades;
   assert no exception + reply persisted (don't over-assert mesh content; assert the step ran/no-op).
6. **`run_escalation_only()` runs ONLY the subset** — unit test on `DmReplyPipeline`: spy/stub the
   17 step methods, call `run_escalation_only()`, assert exactly {4e,4i,4h,4f,4g} invoked and the
   other 12 NOT invoked.
7. **`run()` is unchanged** — same spy approach: `run()` still invokes all 17 in order (regression
   guard for the refactor).
8. **Fan-out still returns one entry per speaker with the (possibly mutated) text** — the
   `group_chat_fanout` return shape `{agent_id, callsign, text}` is preserved; `text` reflects the
   escalated reply.

## Gates
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad933_group_chat_escalation.py -q -n 0 -p no:cacheprovider`
- Blast radius: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "thread or chat or fanout or dm or reply or pipeline or create_task or escalat" -q -p no:cacheprovider`
- No UI change → no Vitest.

## Acceptance criteria
- `_send_one` runs `run_escalation_only()` after a real `result.result`; group `[CREATE_TASK]`
  opens a dispatchable work item; reply persisted with tag stripped + task-id suffix.
- `DmReplyPipeline.run()` behavior byte-identical (all 17 steps, same order, same guard).
- New `run_escalation_only()` runs exactly the 5-step subset.
- 1:1 `/api/agent/{id}/chat` path **unchanged** (it still calls `run()`).
- No mislabeled group episode written (step_5 excluded).
- Both gates green; report counts. Tier-2 honest-degrade on every new failure path.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT (scope fence)
- Do **not** touch the AD-632 chain: `_CHAIN_ELIGIBLE_INTENTS`, `_should_activate_chain`,
  `_execute_chain_with_intent_routing`, `_pending_sub_task_chain`. (In-chat `[THINK]`/`[DELIBERATE]`
  via the dormant escape hatch is a separate, deferred **AD-934** — do not build it.)
- Do **not** change the 1:1 `/chat` flow, `DmReplyContext` fields, or any step method body.
- Do **not** add episodic/working-memory/divergence/emotion/games/image-gen/outbound-DM/avatar
  steps to the group path (forward marker **AD-933a** = correct *group-anchored* episodic write;
  **AD-933b** = optional richer subset).
- Do **not** change the `ChatFacilitator`, fan-out who-speaks/order logic, the `IntentMessage`, the
  vision pipeline, or `AD-925` task-room logic (it fires downstream automatically when a created
  task fans to ≥2 crew).
- Do **not** touch the Ward Room.
- Do **not** push. Commit local only; the Captain decides the push.

## Verified references (HEAD — grep-confirmed, do not re-derive)
- `DmReplyPipeline` / `DmReplyContext`: `src/probos/cognitive/dm/reply_pipeline.py`; import via
  `from probos.cognitive.dm import DmReplyContext, DmReplyPipeline` (exact import used in
  `routers/agents.py`).
- `run()` step tuple = **17 steps** in this order: `step_1_sanity_gate_retry, step_2_challenge_parse,
  step_3_move_parse, step_4_self_check_parse, step_4c_image_gen_parse, step_4d_follow_up_parse,
  step_4e_action_dispatch, step_4b_dm_outbound_parse, step_4i_notebook_parse, step_4h_mesh_read_parse,
  step_4f_extract_artifacts, step_4g_create_task_parse, step_5_episodic_store,
  step_6_working_memory_record, step_7_divergence_check, step_8_mark_emitted, step_9_emotion_resolve`.
- `step_4g_create_task_parse` early-returns when `not self.ctx.response_text or self.ctx.sanity_gate is None`;
  reads `runtime.work_item_store`; calls `store.create_work_item(title=, description=, work_type="task",
  assigned_to=, created_by="captain", metadata={"dispatchable": True}, tags=["yeo-delegated"])`.
- `step_8_mark_emitted` guards `if self.ctx.sampling_state is not None:` and
  `if self.ctx.avatar_event_bus is not None:` — so `None`/`None` makes it a safe no-op (only calls
  `agent.mark_reply_emitted()` if present).
- 1:1 wiring to mirror: `routers/agents.py` `agent_chat`, `result = await runtime.intent_bus.send(intent)`
  (~L2216) → `sanity_gate = getattr(runtime, "dm_sanity_gate", None)` → `DmReplyPipeline(DmReplyContext(...))`
  → `await pipeline.run()` → `pipeline.build_response()` (~L2263–2271).
- Fan-out site: `routers/thread_fanout.py` `group_chat_fanout._send_one`; `agent = runtime.registry.get(agent_id)`
  resolved near top; `params` built ~L278; `result = await runtime.intent_bus.send(intent)` ~L305;
  `reply_text = str(result.result) ...` ~L312; `store.append_message(...)` ~L315. `logger`,
  `IntentMessage`, `from __future__ import annotations` already present.
- Test fixtures: real `WorkItemStore` from `probos.workforce` (class L932, `create_work_item(**kwargs)` L1019);
  real `ChatThreadStore` (`runtime.chat_thread_store`); real `IntentBus(SignalManager(reap_interval=1.0))`;
  real `dm_sanity_gate` (`runtime.dm_sanity_gate`). Harness shape: mirror `tests/test_ad914_*` /
  `tests/test_ad915_*` / `tests/test_ad924_group_chat_trigger.py`.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-933 row, SHIPPED + date + gate note.
- `PROGRESS.md`: prepend an AD-933 block.
- `DECISIONS.md` (or the active era decisions file): AD-933 entry — the 3-mode map, the
  escalation-subset decision + why the full pipeline was rejected (episodic mislabel), forward
  markers AD-933a/AD-933b/AD-934.
- Stage explicit paths (NOT `git add -A`); deletion-audit before commit.
