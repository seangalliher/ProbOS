# AD-933a — Group-anchored episodic write for the fan-out

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-933a** (sub-AD of AD-933). Highest committed: AD-933 (`a7004781`).
**Mode:** Builder. Code + tests + gates + commit local. No push.

## Problem (verified vs HEAD)
Group-chat replies currently write **NO episode at all** — a learning-loop hole:
- The fan-out sends `direct_message` with `params["from"]="hxi_profile"` (`thread_fanout.py` `_send_one`, ~L280).
- The agent's universal episodic safety-net `_store_action_episode` (`cognitive_agent.py:8034`) **skips**
  exactly that case: `if intent.intent == "direct_message" and source in ("hxi_profile","captain"): return`
  — it defers to the pipeline's `step_5_episodic_store`.
- AD-933 deliberately **excluded** `step_5` from the group subset (it hardcodes `session_type:"1:1"`/
  `channel:"dm"`, which would mislabel a multi-agent turn).
- Net: neither path writes a group episode. Agents don't remember what they said in a room — no episodic
  recall, no dreaming consolidation, no wellness/divergence analysis. Violates "every execution path stores
  an episode or the learning loop breaks."

## Precedent (mirror this exactly)
The AD-719 @-mention fan-out already writes a correct group-shaped episode per reply
(`routers/chat.py` ~L215–L256): for each resolved reply it uses `dream_adapter.build_episode(...)` when
`runtime.dream_adapter` exists, else falls back to a direct
`Episode(timestamp=time.time(), user_input=episode_input, dag_summary={}, outcomes=[], agent_ids=[agent_id],
duration_ms=..., source="multi_agent_chat", anchors=AnchorFrame(channel="chat", trigger_type="at_mention_fanout"))`,
then `await episodic_memory.store(episode)` inside a Tier-2 `try/except` that logs and continues.

## Change — `src/probos/routers/thread_fanout.py`, `group_chat_fanout` only
After `replies = await asyncio.gather(*[_send_one(a) for a in speaking_order])` (end of the function, ~L364),
add a Tier-2 episodic-write loop mirroring the AD-719 precedent, BUT group-anchored:
- Guard: `episodic_memory = getattr(runtime, "episodic_memory", None)`; if `None`, skip entirely.
- Resolve participants once: `["captain"] + [callsign-or-agent_id for each crew speaker]` for the AnchorFrame.
- For each `reply` in `replies`:
  - Skip if `not reply["agent_id"]` or `reply["text"]` in the sentinel set `{"(no response)", "(delivery failed)", ""}`.
  - Build the episode (prefer `runtime.dream_adapter.build_episode(episode_input, {...}, t_start, t_end)` when
    `dream_adapter` is present — capture `t_start = time.monotonic()` at the TOP of `group_chat_fanout` and
    `t_end` after the gather; else the direct fallback `Episode(...)`).
  - `episode_input = f"[group chat] Captain: {captain_body[:200]}"`.
  - Anchors: `AnchorFrame(channel="chat", trigger_type="group_fanout", participants=<resolved list>, chat_thread_id=thread_id)`.
  - `source="group_chat_fanout"` (a distinct tag, parallel to AD-719's `"multi_agent_chat"`).
  - `outcomes=[{"intent":"direct_message","success":True,"response":reply["text"][:500],"session_type":"group","callsign":reply["callsign"],"source":"group_chat_fanout"}]`.
  - `agent_ids=[reply["agent_id"]]`.
  - `await episodic_memory.store(episode)` inside `try/except Exception` → `logger.warning("AD-933a: group episode store failed for %s: ...; continuing", ...)`. NEVER raises.

Notes:
- `Episode`/`AnchorFrame` import: `from probos.types import AnchorFrame, Episode` (local import inside the
  function, matching the chat.py fallback-branch style).
- Do NOT touch `_send_one`'s return shape, the pipeline, `_store_action_episode`, or `step_5`.
- Do NOT change the 1:1 path. This is additive, group-only.

## Tests — `tests/test_ad933a_group_episode.py` (BF-287 real fixtures), floor +6
Real `ChatThreadStore` (tmp), real `IntentBus(SignalManager(reap_interval=1.0))`, a recording
`episodic_memory` stub exposing `async def store(self, episode)` that appends to a list (a real-but-fake
recorder, NOT MagicMock), a real-but-fake registry/agent that returns a canned reply via a subscribed
`direct_message` handler. Mirror `tests/test_ad914_*`/`tests/test_ad915_*`.
1. **One episode per crew reply** — 2-crew thread + captain turn → exactly 2 episodes stored.
2. **Group-anchored** — stored episode has `anchors.channel == "chat"`, `anchors.trigger_type == "group_fanout"`,
   `outcomes[0]["session_type"] == "group"`, and `anchors.chat_thread_id == thread_id`. NOT `"1:1"`/`"dm"`.
3. **Participants** — `anchors.participants` contains `"captain"` + both crew ids/callsigns.
4. **Sentinel replies skipped** — an agent returning `"(no response)"` produces no episode.
5. **`episodic_memory is None` degrades** — no crash, replies still returned.
6. **`store()` raising degrades** — a recorder that raises on the first call still lets the fan-out return all
   replies (Tier-2), and the second reply's episode still attempts to store.

## Gates
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad933a_group_episode.py -q -n 0 -p no:cacheprovider`
- Blast: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "thread or chat or fanout or episod or dream" -q -p no:cacheprovider`
- No UI change → no Vitest.

## Acceptance
- Each crew fan-out reply writes exactly one `channel="chat"`/`session_type:"group"` episode tagged with the
  thread id; sentinels skipped; Tier-2 honest-degrade on every failure path; 1:1 path unchanged.
- Verify compliance with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT
- No change to `_send_one` return shape, `DmReplyPipeline`, `_store_action_episode`, `step_5`, the 1:1 path,
  the facilitator, `IntentMessage`, or the Ward Room. No push. Stage explicit paths (NOT `git add -A`);
  deletion-audit before commit.

## Trackers (after gates green)
- roadmap row AD-933a SHIPPED + date; PROGRESS.md block; DECISIONS.md AD-933a entry (the verified no-episode
  gap + the mirror-AD-719 fix + why step_5 stays excluded).
