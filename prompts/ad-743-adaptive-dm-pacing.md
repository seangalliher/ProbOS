# AD-743 — Adaptive conversational pacing in active 1:1 DMs

**Issue:** [#662](https://github.com/seangalliher/ProbOS/issues/662)
**Status:** GATE 1 — drafting (Wave 176)
**Depends on:** AD-722 (`mark_reply_emitted` / `last_reply_emitted_at` already shipped), AD-728c (two-budget pattern), AD-724 (`DmReplyPipeline` step structure), AD-730-3 (`[GEN_IMAGE ...]` bracket-marker precedent), AD-733c-1 (force-describe DM hook).
**Estimated tests:** +12 pytest, +0 vitest.

---

## Problem

In 1:1 DM chats, agents are strictly turn-taking: agent replies once,
then waits silently for Captain to send the next message. There is no
mechanism for multi-beat replies, ambient follow-ups, or curiosity on
silence within an active DM session.

This is distinct from proactive DMs (AD-733b ProactiveVisionObserver
already covers cross-conversation pings). The gap is conversational
adaptiveness WITHIN an active DM session.

## Solution

Three-part minimal landing:

1. **New `[FOLLOW_UP delay_seconds reason]` bracket marker** — extends
   the AD-572 / AD-730-3 bracket-marker family. Parsed in a new
   `step_5_follow_up_parse` stage of `DmReplyPipeline` after
   `step_4_self_check_parse`. Reason is `[a-z_-]{1,64}`; delay is
   `1..300` seconds. Malformed markers silently stripped (no Captain-
   visible leakage).

2. **New `ConversationPacingScheduler` runtime service** —
   `src/probos/cognitive/dm/pacing_scheduler.py`. Owns `asyncio.Task`
   refs per `(agent_id, conversation_id)`, schedules a synthesized
   user-turn `IntentMessage(intent="direct_message", params={"text":
   "[CONVERSATION_FOLLOW_UP reason=<reason>]", "from": "pacing_scheduler",
   ...})` after `delay_seconds`. Cancelled if the Captain sends a new
   DM in the meantime (interruption wins). Single-flight per agent +
   conversation; new FOLLOW_UP from a later reply overrides the
   pending one.

3. **Two-budget rate limit** (AD-728c precedent):
   - `pacing_max_followups_per_active_conversation` (default 2,
     scope `pacing_conv:<last_reply_ts>` — resets when the
     last_reply_emitted_at advances by more than the active window).
   - `pacing_max_followups_per_hour_per_agent` (default 6, hourly
     hard ceiling).
   - Budgets are NOT additive — per-conversation budget is the
     in-conversation ceiling; hourly is the safety cap.

4. **Captain-silence "Still there?" trigger** — DEFERRED to forward
   marker `AD-743-1`. v1 ships agent-initiated multi-beat + follow-up
   ONLY. Silence detection adds an idle-watcher that's a separate
   loop. Keep this build tight.

## Cross-AD interaction notes

- **DOES NOT replace** the existing `agent_chat` → `DmReplyPipeline`
  path. Scheduler is a sibling service owned by `runtime`.
- **REUSES** `IntentMessage` + `intent_bus.send` (no new wire
  format). The synthesized user-turn carries a bracket marker the
  agent can detect — agent's own LLM composes the visible follow-up
  using its voice profile (same pattern as AD-733b proactive observer:
  the runtime never composes user-facing text).
- **REUSES** `last_reply_emitted_at` (AD-722) as the
  conversation-active signal — no new state.
- **AD-733c-1 force_describe + AD-733c-2 note_dm_activity** continue
  to fire on the synthesized user-turn (it is a `direct_message`);
  this is intentional — perception stays alive during multi-beat
  conversations. (NOTE: confirm with grep that the synthesized
  message does not re-fire the AD-722f sampling-state enter_dm; it
  should — the agent IS replying. Already-engaged refresh is the
  acceptable shape per AD-722f's clamp logic.)
- **NOT a skill** — Captain's issue mentions "skill-shaped per the
  self-image-awareness precedent." Decided against: skills are
  cognitive policies; pacing is a runtime cadence service. A skill
  cannot hold `asyncio.Task` references. The agent COULD have a
  "conversational-pacing" skill that teaches WHEN to emit the marker
  (system-prompt-injected via `instructions`) — that is a separate,
  zero-code addition the operator can drop in `config/skills/` after
  this AD lands.

## Scope

- New file: `src/probos/cognitive/dm/pacing_scheduler.py`
  (~150-200 lines: `ConversationPacingScheduler` class with `start`,
  `stop`, `schedule_followup`, `cancel_for_conversation`,
  `pending_followups` properties).
- New regex in `cognitive/dm_sanity_gate.py`:
  `_FOLLOW_UP_RE = re.compile(r"\[FOLLOW_UP\s+(\d{1,3})\s+([a-z_-]{1,64})\]")`
  + `_FOLLOW_UP_STRIP_RE` lax-strip (mirror AD-728d / AD-730-3
  precedent).
- New extraction method on `DmSanityGate`: `extract_followup(text) ->
  tuple[int, str] | None` and `strip_followup(text)`.
- New step in `cognitive/dm/reply_pipeline.py`:
  `step_5_follow_up_parse` inserted in the `_steps` tuple AFTER
  `step_4_self_check_parse`.
- New config block on `AvatarsConfig` (NOT a new top-level config —
  pacing belongs with conversational behavior):
  - `pacing_enabled: bool = False` (default-OFF transitional gate,
    convention #14).
  - `pacing_max_followups_per_active_conversation: int = 2`
    (`ge=0, le=10`).
  - `pacing_max_followups_per_hour_per_agent: int = 6`
    (`ge=0, le=60`).
  - `pacing_active_window_seconds: int = 600` (mirrors AD-728c).
  - `pacing_min_delay_seconds: int = 1` (`ge=1, le=60`).
  - `pacing_max_delay_seconds: int = 300` (`ge=1, le=900`).
- `startup/finalize.py`: construct
  `runtime.conversation_pacing_scheduler = ConversationPacingScheduler(...)`
  when `cfg.avatars.pacing_enabled` is True; `await scheduler.start()`.
- `startup/shutdown.py`: `await runtime.conversation_pacing_scheduler.stop()`
  (mirrors `recording_reaper` / `perception_mode_controller` shape).
- `routers/agents.py:agent_chat`: BEFORE the `mark_reply_emitted` call,
  invoke `scheduler.cancel_for_conversation(agent_id, conversation_id)`
  (Captain's new message interrupts pending follow-up). AFTER the reply
  pipeline runs, if the agent's response carried a follow-up marker,
  schedule it.

## NOT in scope

- Captain-silence "Still there?" trigger → AD-743-1 forward marker.
- Multi-message split within a single agent reply (e.g. emit
  `[FOLLOW_UP 0 split]` as a synchronous second message) — only
  delay >= `pacing_min_delay_seconds` (default 1s) is supported in
  v1. Same-tick splits are a separate UX concern (chunked rendering),
  filed as AD-743-2.
- WardRoom / multi-agent thread pacing — explicitly 1:1 DM only.
- Skill-shaped `conversational-pacing.yaml` manual — operator-droppable
  after this AD lands; not part of the build.
- AD-728c-1 per-conversation budget reset on Captain-acknowledged
  correction — same forcing function applies here but the budget reset
  semantics deserve their own AD (AD-743-3 if needed).

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `src/probos/cognitive/dm_sanity_gate.py:46` —
   `_SELF_CHECK_RE = re.compile(...)` exists as the precedent regex
   pattern. New `_FOLLOW_UP_RE` inserted immediately after the
   `_SELF_CHECK_STRIP_RE` block.
2. `src/probos/cognitive/dm/reply_pipeline.py:82` — the `_steps`
   tuple defines the pipeline order. Verify `step_4_self_check_parse`
   is at index 4; insert `step_5_follow_up_parse` at index 5.
3. `src/probos/cognitive/cognitive_agent.py:3090` —
   `def mark_reply_emitted(self) -> None:` is the canonical
   conversation-active stamp. Pacing scheduler reads
   `agent.last_reply_emitted_at` (property at line 3115); NEVER touch
   `_last_reply_emit_ts` directly.
4. `src/probos/routers/agents.py:1660` — `async def agent_chat(...)`
   is the single ingress. The scheduler's `cancel_for_conversation`
   call inserts BEFORE the existing `mark_reply_emitted` site (Builder
   greps for `mark_reply_emitted` callsite inside `agent_chat`).
5. `src/probos/startup/finalize.py:4133` —
   `runtime.perception_mode_controller = _controller` is the canonical
   shape for "lifecycle service wired in finalize." Mirror for
   `conversation_pacing_scheduler`.
6. `src/probos/startup/shutdown.py` — find the `recording_reaper.stop()`
   await pattern (anchor via grep). Mirror it.

## Engineering-principles audit

- **SOLID load-bearing**: Single Responsibility — scheduler owns
  *only* "deliver a synthesized user-turn after delay_seconds." It does
  NOT compose text, does NOT touch trust/Hebbian, does NOT write to
  episodic memory.
- **Defaults preserve behavior**: `pacing_enabled=False` default.
  Existing DM path bit-for-bit unchanged when disabled.
- **AD-731 invariant**: N/A (no image bytes). Confirm via source-scan
  test that `pacing_scheduler.py` contains no `b64encode`,
  `base64.b64`, `attachment_ref`.
- **AD-541b memory integrity**: Synthesized follow-up user-turn carries
  `from: "pacing_scheduler"` so episodic-recall and AD-541b
  reconsolidation know this is system-synthesized, not Captain-
  authored. The agent's response to the follow-up IS a real reply,
  anchored normally.
- **Hot-reload posture (BF-308)**:
  - `pacing_enabled` master toggle → restart-required (changes
    `runtime` attribute presence).
  - All cap values (max_followups_*, min/max delay) → hot-reload via
    BF-308 setter pattern (scheduler reads from `runtime.config` on
    every schedule call; no caching).
- **Anti-deadlock**: `schedule_followup` is sync (just spawns a task).
  The scheduled task `await self._runtime.intent_bus.send(intent)`
  holds no scheduler lock during the wait. `cancel_for_conversation`
  holds only the per-agent dict lock for milliseconds.
- **Async discipline**: Every `asyncio.create_task()` call stores the
  reference in `self._pending_tasks: dict[tuple[str, str],
  asyncio.Task]`. CancelledError caught + re-raised in `_emit_followup`.
- **License posture**: 0-line diff on `pyproject.toml`, `package.json`,
  `package-lock.json`, `THIRD_PARTY_LICENSES.md`, `.gitignore`. Pure
  stdlib + existing IntentBus.
- **Test scaffolding**: real `SystemConfig()` + real
  `AvatarsConfig(pacing_enabled=True)` (BF-287). Fake intent_bus via
  dataclass stub. NO MagicMock at substrate boundary.
- **HXI compliance**: N/A — no UI surface in v1. The follow-up appears
  as a normal agent message in the existing DM chat surface.

## Test plan (+12 pytest)

`tests/test_ad743_adaptive_dm_pacing.py`:

1. `test_followup_regex_extracts_well_formed` — `[FOLLOW_UP 5 mid_thought]`
   → `(5, "mid_thought")`.
2. `test_followup_regex_rejects_invalid_delay` — `[FOLLOW_UP 0 x]`,
   `[FOLLOW_UP 9999 x]`, `[FOLLOW_UP abc x]` all return None.
3. `test_followup_strip_removes_both_forms` — well-formed AND
   malformed markers stripped from Captain-visible text.
4. `test_scheduler_schedules_after_delay` — real `asyncio.wait_for`,
   verifies synthesized intent lands on the (fake) bus after the
   delay window elapses.
5. `test_scheduler_cancels_on_captain_interruption` —
   `cancel_for_conversation` while task pending → no intent sent.
6. `test_scheduler_per_conversation_budget` — third follow-up in
   active conversation refused; logs WARNING.
7. `test_scheduler_hourly_budget_ceiling` — 7th in one hour refused
   even across multiple conversations.
8. `test_scheduler_budgets_NOT_additive` — verifies per-conversation
   budget IS the cap when conversation is active (mirrors AD-728c
   Test 5).
9. `test_pacing_disabled_default_no_scheduler` — `pacing_enabled=False`
   → `runtime.conversation_pacing_scheduler is None`; existing
   DmReplyPipeline still runs but step_5 is a no-op.
10. `test_step_5_in_pipeline_order` — `_steps` tuple includes
    `step_5_follow_up_parse` at index 5.
11. `test_synthesized_followup_carries_from_marker` — synthesized
    `IntentMessage` has `params["from"] == "pacing_scheduler"` (for
    AD-541b anchor distinguishability).
12. `test_ad731_invariant_no_inline_base64_in_pacing_module` —
    source-scan asserts ZERO `b64encode` / `base64.b64` /
    `attachment_ref` in `pacing_scheduler.py`.

## Tracker updates (Builder)

- `PROGRESS.md` — add Wave 176 line under "Wave 176 in flight" with
  the AD-743 summary.
- `docs/development/roadmap.md` — add row:
  `| AD-743 | Adaptive conversational pacing in active 1:1 DMs ... | #662 | 2 |`
  and forward markers AD-743-1 (Captain silence), AD-743-2 (same-tick
  multi-message), AD-743-3 (correction-driven budget reset).
- `DECISIONS.md` — append AD-743 entry at build time (NOT now).

## Acceptance criteria

1. `pacing_enabled=False` (default) → all existing DM behavior bit-for-
   bit unchanged. `test_ad724_dm_sanity_gate.py` + `test_ad728d_self_check.py`
   pass without modification.
2. `pacing_enabled=True` + agent emits `[FOLLOW_UP 2 mid_thought]` in
   reply → after 2s, a synthesized user-turn lands on the bus targeted
   at the same agent with `from: "pacing_scheduler"`.
3. Captain sends a new DM while a follow-up is pending → pending task
   cancelled; new DM proceeds normally; no double-fire.
4. Budgets enforced; WARNING logged once per exhaustion event.
5. All 12 tests pass.
6. `cd ui && npx vitest run` and `cd ui && npm run build` exit 0
   (no UI changes expected, but bundle integrity must be verified per
   BF-279).
7. Zero new pip / npm deps. 0-line diff on all 5 license files.
8. Source-scan tests for AD-731 invariant + bracket-marker
   precedent pattern green.
9. **Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.**
