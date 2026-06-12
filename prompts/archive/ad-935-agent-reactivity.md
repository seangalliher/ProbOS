# AD-935 — Agent-to-agent group-chat reactivity (bounded synchronous cascade)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-935.** Highest committed+pushed: AD-934 (`69e99630`).
**Mode:** Builder. Code + tests + gates + commit local. No push.

## Problem (Captain-reported, verified vs HEAD)
In a group chat, agents only respond when the **Captain** posts. If agents ask each *other* questions, there
is **no reply until the Captain sends another message.** The Captain's words: *"they should get notified when
a message is sent in a chat they are in and then they can determine if the response is required. Since this
is a real time chat it should trigger them to respond right away."*

Root cause: the group fan-out fires ONLY on `role=="captain"` (`routers/threads.py` `append_message`,
`if body.role == "captain":` ~L373). An agent reply is persisted (`store.append_message(..., role="agent")`)
but nothing re-fans to peers. AD-914 deliberately bounded the fan-out to "fan once and STOP" (no a2a) to
avoid loops; AD-935 adds **bounded** agent-to-agent reactivity.

## Architecture decision — BOUNDED SYNCHRONOUS cascade (NOT async)
**Verified constraint:** the chat transcript has **no live-refresh** — there is no polling loop and no
WebSocket case for chat messages (`ui/src/store/useStore.ts` `handleEvent` has no `chat_message`/
`thread_message` case; `ProfileChatTab` renders only what the send POST returns in `per_agent_replies`). So a
fire-and-forget async cascade would create messages the UI never shows until manual refresh, AND is harder to
bound. Therefore AD-935 runs the cascade **synchronously within the Captain's POST** and returns ALL cascade
replies (across rounds) in the existing `per_agent_replies` list — which the UI already renders, in order.
(True streaming/async reactivity is a forward marker **AD-935a**, unlocked once a live-refresh exists.)

This mirrors the Ward Room's round-capped a2a reactivity, but on `ChatThreadStore` and synchronous. The
**`ChatFacilitator` convergence gate (AD-915) is the semantic terminator**: fed the growing agent-message
window, it returns an empty `speaking_order` once the exchange converges. The round cap is the hard backstop.

## The cascade (precise)
- **Round 0** (unchanged behavior): Captain message → facilitator picks `speaking_order` → parallel dispatch
  → persist each reply → AD-933a episodic write. Collect round-0 replies.
- **Rounds 1..max_agent_rounds** (only when `group_chat.agent_reactivity_enabled` is True): each round fans
  the **previous round's new agent messages** to the OTHER crew (excluding the agents who just spoke in that
  round), gated by the facilitator (convergence → empty → STOP) and `[NO_RESPONSE]` (decline → not persisted,
  not propagated). A round that produces zero non-decline replies STOPS the cascade.
- All replies across all rounds return as one flat `per_agent_replies` list (UI renders in order). No reply
  shape change — still `{agent_id, callsign, text}` per entry.

Termination conditions (any): facilitator `converged` / empty `speaking_order`; round cap reached; a round
produced zero non-`[NO_RESPONSE]` replies; reactivity flag off (no cascade at all).

## Changes

### 1. `src/probos/config.py` — `GroupChatConfig` (add 2 fields, default-safe)
After `auto_task_room_enabled: bool = False` (~L3771) add:
```python
    # AD-935: bounded synchronous agent-to-agent reactivity. When enabled, an
    # agent reply in a group chat fans to the OTHER crew for up to
    # ``max_agent_rounds`` extra rounds, gated by the AD-915 convergence gate
    # + [NO_RESPONSE]. Transitional flag (#14) — ships OFF; system.yaml flips it
    # on. Synchronous within the Captain turn (no live-refresh exists yet).
    agent_reactivity_enabled: bool = False
    max_agent_rounds: int = 2   # extra agent-only rounds after the Captain round (0 = AD-914 single round)
```
Zero-config boot stays byte-identical (flag OFF → no cascade).

### 2. `config/system.yaml` — flip it ON for the operator
In the `group_chat:` block (~L1829, next to `auto_task_room_enabled: true`) add:
```yaml
  agent_reactivity_enabled: true
  max_agent_rounds: 2
```
(AD-925 precedent: default False in Pydantic, true in system.yaml.)

### 3. `src/probos/routers/thread_fanout.py` — extract a per-round unit + add the cascade loop
**Extract** the existing single-round core of `group_chat_fanout` (facilitate → `gather(_send_one)` → AD-933a
episodic write) into a helper:
```python
async def _fan_one_round(
    runtime, store, thread_id, *, trigger_body, candidate_ids, exclude_ids,
    vision_messages, sanity_gate, t_start,
) -> list[dict[str, str]]:
    """One reactivity round: facilitate over candidate_ids (minus exclude_ids)
    using trigger_body for mention/relevance, dispatch the chosen speakers in
    parallel (the existing _send_one), persist non-[NO_RESPONSE] replies, write
    AD-933a group episodes, and return the new {agent_id, callsign, text}
    replies. Returns [] when the facilitator suppresses everyone (converged /
    empty)."""
```
- `_fan_one_round` rebuilds the prior window from the store each call
  (`store.list_messages(thread_id, limit=1000)` — INCLUDING the just-persisted prior-round replies),
  recomputes `session_history` via `_build_session_history` (so each speaker sees the full transcript),
  recomputes `_assemble_speaker_signals(runtime, trigger_body, [candidate_ids minus exclude_ids], prior)`, and
  the recent-agent-messages window for `facilitator.facilitate`.
- `vision_messages` is passed only for round 0 (Captain attachments); `None` for agent rounds.
- The AD-933a episodic-write block moves INTO `_fan_one_round` (one episode per persisted reply, unchanged
  anchors/shape). The `t_start` is threaded in for `build`/duration parity.

**Rewrite** `group_chat_fanout` as the orchestrator:
```python
async def group_chat_fanout(runtime, thread_id, *, captain_body, captain_msg) -> list[dict[str, str]]:
    # ... resolve store/thread, sanity_gate (once), vision_messages (round 0 only), t_start ...
    all_replies: list[dict[str, str]] = []
    round0 = await _fan_one_round(..., trigger_body=captain_body, candidate_ids=<all crew>,
                                  exclude_ids=set(), vision_messages=vision_messages, sanity_gate=sanity_gate, ...)
    all_replies.extend(round0)
    cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
    if getattr(cfg, "agent_reactivity_enabled", False):
        max_rounds = int(getattr(cfg, "max_agent_rounds", 2))
        last = round0
        for _ in range(max(0, max_rounds)):
            spoke_ids = {r["agent_id"] for r in last if r.get("agent_id")}
            if not spoke_ids:
                break  # nothing new to react to
            trigger = "\n".join(f"{r['callsign']}: {r['text']}" for r in last)
            nxt = await _fan_one_round(..., trigger_body=trigger, candidate_ids=<all crew>,
                                       exclude_ids=spoke_ids, vision_messages=None, sanity_gate=sanity_gate, ...)
            if not nxt:
                break  # facilitator converged / suppressed everyone / all declined
            all_replies.extend(nxt)
            last = nxt
    return all_replies
```
Notes: `exclude_ids` prevents an agent from immediately replying to its own round; the facilitator's
convergence gate (reading ALL recent agent messages) is the primary terminator. The cascade is synchronous
(awaited), bounded by `max_rounds`, and degrades Tier-2 (any round failure logs + returns what it has).

### 4. `src/probos/routers/thread_fanout.py` `_send_one` — honor `[NO_RESPONSE]`
After computing `reply_text` (and after the AD-933 escalation), treat a decline as "no reply":
```python
# AD-935: an agent may decline to respond in a group turn. A [NO_RESPONSE]
# (case-insensitive, after strip) or empty reply is NOT persisted and NOT
# returned — so it neither shows in the transcript nor propagates the cascade.
if reply_text.strip().upper().replace("[", "").replace("]", "") == "NO_RESPONSE" or not reply_text.strip():
    return {"agent_id": agent_id, "callsign": callsign, "text": "", "_declined": True}
```
The round collector (`_fan_one_round`) filters out `_declined`/empty entries BEFORE persisting + before
returning, so declines never reach `append_message`, the episode write, or `per_agent_replies`. (This also
fixes round-0: today a literal `[NO_RESPONSE]` would be persisted + shown.)

### 5. `src/probos/cognitive/cognitive_agent.py` — teach the group decline option (so `[NO_RESPONSE]` is used)
The fan-out passes `params["is_group_chat"] = True` (round 0 AND cascade rounds — set in `_send_one`'s param
dict, or pass through `_fan_one_round`). Add an overridable hook next to `_conversational_deliberate_protocol`
(~L1912), invoked in the conversational branch next to `_delib_proto` (~L2399):
```python
def _conversational_group_chat_protocol(self, observation: dict) -> str:
    """AD-935: in a group chat, teach the agent that responding is OPTIONAL —
    reply only with something substantive to add, else decline. Gated on the
    group fan-out param so 1:1 DMs are unaffected. Universal (all crew), like
    the AD-912 notebook capability. Gap-regex-safe."""
    params = observation.get("params") or {}
    if not params.get("is_group_chat"):
        return ""
    return (
        "\n\nYou are in a group chat with other crew. Reply ONLY when you have "
        "something substantive to add, build on, answer, or correct. If a "
        "fellow crew member directs a question to you, answer it. When you have "
        "nothing to add, respond with exactly [NO_RESPONSE] and nothing else."
    )
```
**Gap-regex safety (memory: `_CAPABILITY_GAP_RE`):** the string must NOT contain "can't"/"cannot"/"don't
have"/"unable to"/"not able to". The wording above avoids them — keep it that way; verify before shipping.

## Tests — `tests/test_ad935_group_reactivity.py` (BF-287 real fixtures), floor +12
Real `ChatThreadStore` (tmp), real `IntentBus(SignalManager(reap_interval=1.0))`, real-but-fake
registry/agents whose subscribed `direct_message` handlers return SCRIPTED replies keyed by round/agent
(NOT MagicMock), real `GroupChatConfig` with `agent_reactivity_enabled` toggled per test, a recording
`episodic_memory` stub. Mirror `tests/test_ad914_*`/`tests/test_ad915_*`/`tests/test_ad933a_*`.
1. **Flag OFF = AD-914 single round** — Captain post → exactly one round of replies; no cascade; existing
   AD-914/915 tests stay green (run them).
2. **Flag ON, agents converse** — round-0 agent A asks "@Bones thoughts?"; round 1 Bones responds; assert
   `per_agent_replies` contains BOTH rounds in order; Bones' round-1 reply is persisted as role="agent".
3. **Round cap stops it** — every agent always replies (scripted, never declines); assert total rounds ==
   1 + `max_agent_rounds` (no more), even though agents would keep going.
4. **Convergence stops it** — scripted replies are near-identical (high Jaccard) across ≥`convergence_min_
   messages` from ≥`convergence_min_agents`; assert the cascade stops early (facilitator `converged` →
   empty speaking_order) BEFORE the round cap.
5. **`[NO_RESPONSE]` not persisted, not propagated** — an agent returns `[NO_RESPONSE]`; assert it is NOT in
   `per_agent_replies`, NOT in the thread messages, and does not extend the cascade.
6. **`[NO_RESPONSE]` round-0 fix** — a round-0 agent declines; the other agent's real reply still returns;
   the decline is absent from the transcript.
7. **Exclude-author** — an agent does not immediately respond to its own message within the next round
   (it's in `exclude_ids`).
8. **All-decline stops** — a round where every candidate declines ends the cascade (no empty infinite loop).
9. **@-mention bypass** — an agent @-mentioned by a peer is in the next round's `speaking_order` even under a
   `max_speakers_per_turn` cap.
10. **AD-933a episode per cascade reply** — each persisted cascade reply writes one group-anchored episode
    (channel="chat", session_type="group").
11. **`_conversational_group_chat_protocol`** — returns "" without the `is_group_chat` param; non-empty with
    it; the string contains NO `_CAPABILITY_GAP_RE` phrase.
12. **Tier-2 honest-degrade** — a round whose dispatch raises does not crash the turn; `group_chat_fanout`
    returns the replies gathered so far.

## Gates (run both, report exact counts)
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad935_group_reactivity.py -q -n 0 -p no:cacheprovider`
- Blast: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "thread or chat or fanout or facilitat or convergence or reply or pipeline or group or cognitive_agent" -q -p no:cacheprovider`
  (large ~3 min; `-q`, tail, NO `-x`. Pre-existing `test_skill_agent.py::TestSkillPipeline` serial-isolation
  flakes are KNOWN — if they appear, re-run that file alone with `-n 0` to confirm green in isolation and
  report as pre-existing, not a regression.)
No UI change → no Vitest.

## Acceptance
- Flag OFF → byte-identical AD-914 single round; zero-config boot unchanged.
- Flag ON → agents react to each other for up to `max_agent_rounds` extra rounds, all replies returned in
  `per_agent_replies` (in order), bounded by convergence + round cap + all-decline.
- `[NO_RESPONSE]` declines are never persisted/shown/propagated (round 0 AND cascade).
- Each persisted cascade reply writes an AD-933a group episode; the teaching protocol is gap-regex-safe and
  only appears in group chats.
- Both gates green (modulo known skill-pool flakes). Verify Engineering-Principles compliance.

## Do NOT (scope fence)
- Do **not** make the cascade async / fire-and-forget (no `asyncio.create_task` background cascade) — that is
  forward marker **AD-935a** (needs the live-refresh from a future AD).
- Do **not** add a WebSocket/poll for chat messages (that's the AD-936 family / AD-935a).
- Do **not** change the `{agent_id, callsign, text}` reply shape, the `direct_message` intent, the
  `DmReplyPipeline`, the AD-934 step, the AD-933b ref surfacing, `IntentMessage`, or the Ward Room.
- Do **not** trigger the cascade from agent-INITIATED posts (AD-918/AD-924) — only from the Captain-turn
  fan-out for now (forward marker **AD-935b**: cascade on agent-initiated group posts).
- Do **not** add trust/Hebbian updates from a2a chat exchanges (forward marker **AD-935c**).
- No push. Stage explicit paths (NOT `git add -A`); deletion-audit before commit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-935 row, SHIPPED + 2026-06-08 + gate note.
- `PROGRESS.md`: prepend an AD-935 block.
- `DECISIONS.md` (match where AD-934 went): AD-935 entry — synchronous-bounded chosen over async (no
  live-refresh; bounded is safer), the cascade + guard set (round cap + convergence + `[NO_RESPONSE]` +
  exclude-author + @-mention), flag default OFF / system.yaml ON, forward markers AD-935a (async/streaming
  once live-refresh exists), AD-935b (agent-initiated cascade), AD-935c (trust/Hebbian from a2a).
