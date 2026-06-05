# AD-845/846/847 — Yeo Async Task Workflow (chat → task → kanban → research → completion DM → desktop notice)

**Status:** Draft for review (Architect-authored, verify-first)
**Mode:** Architect spec. Builder executes one AD = one commit. Do NOT build all three in one pass without a gate between them.
**Author note:** Every file/line reference below was grepped against HEAD (`fac6bb68`) before drafting. Builder must still re-verify before editing (subagent/spec reports are leads, not ground truth).

---

## AD numbering — hard rule honored

- **Highest *committed* AD = AD-839** (DECISIONS.md). BF-599 (Wave 209) is the most recent shipped change.
- AD-840–844 are **reserved** by an *uncommitted* `docs/development/roadmap.md` edit (the "Desktop Management Console" block, GH issues #819–822). BF-599's DECISIONS entry also forward-marks AD-840 for "auto-delegation (D2)". To avoid the collision, **this epic does NOT use 840–844.**
- **This epic = AD-845 (Phase 1), AD-846 (Phase 2), AD-847 (Phase 3).** BF-599b (the deferred D2 auto-delegation follow-up) is **subsumed by AD-845** — when AD-845 ships, update the BF-599 forward-marker to read "AD-845" instead of "BF-599b / AD-840".

---

## The desired experience (Captain's words)

> Open a chat with Yeo → "Go research the new Nvidia SPARK RTX devices and provide an analysis." → Yeo creates a **task** that appears on the **kanban board** I can track → I can **keep chatting** with Yeo while it runs → Yeo **DMs me** when it's done → I see the message in our **1:1 chat** *and* waiting in the **Ward Room DMs** → I also get a **desktop notification** that opens the Yeo chat.

## What ALREADY EXISTS (verified — do not rebuild)

| Capability | Where (verified) |
|---|---|
| Task/work-item model + states | `WorkItemStatus` [workforce.py:41](../src/probos/workforce.py); `WorkItem` dataclass; `create_work_item` [workforce.py:992](../src/probos/workforce.py), `update_work_item` [workforce.py:1108](../src/probos/workforce.py) |
| Kanban UI + REST | `POST /api/work-items` [routers/workforce.py:103](../src/probos/routers/workforce.py); HXI Work tab `ProfileWorkTab.tsx` |
| **End-to-end task execution** | **AD-834**: a WorkItem with `description` + `metadata.dispatchable=true` + `assigned_to` is routed by `WorkItemRouter` [mesh/work_item_router.py:104](../src/probos/mesh/work_item_router.py) to the assigned `CognitiveAgent` (perceive→decide→act, tool/web access). **The research runs itself once the item exists.** |
| Dispatch awareness on the agent | `CognitiveAgent._handle_work_item_dispatch` [cognitive_agent.py:1082](../src/probos/cognitive/cognitive_agent.py) (AD-839) |
| Web research tools | BF-599: `WebSearchAgent` + `PageReaderAgent`, live pools, mesh-fetched (DuckDuckGo, no API key) |
| Chat continues while task runs | Conversational path (`direct_message`) is separate from task execution; background tasks via `DAGExecutor` |
| Ward Room DM to Captain | AD-485 pattern [proactive.py:3861-3886](../src/probos/proactive.py): find/create `dm-captain-{agent.id[:8]}` channel (`channel_type="dm"`) → `rt.ward_room.create_thread(channel_id, author_id, title, body, author_callsign)` |
| Completion event | `WORK_ITEM_STATUS_CHANGED` [events.py:100](../src/probos/events.py) emitted on every status change |
| Desktop notification primitive | `notify(args, activator)` with click-routing [desktop/src/main/notifications.ts:22](../desktop/src/main/notifications.ts); `ipcMain` wired in [desktop/src/main/index.ts](../desktop/src/main/index.ts) |
| In-chat reply tag precedent | `[MOVE pos]` parse/strip in [dm_sanity_gate.py:41](../src/probos/cognitive/dm_sanity_gate.py); DM handler is `routers/agents.py:agent_chat` |

**Net gap:** (1) Yeo creating the dispatchable work item **from a 1:1 chat reply**; (2) a listener that turns task completion into a proactive Captain DM; (3) a desktop event→`notify()` bridge. That's it.

---

## AD-845 — Yeo creates a dispatchable task from chat

**Problem.** Yeo's 1:1 chat goes through the *conversational* path (`is_conversation`, [cognitive_agent.py:2200-2228](../src/probos/cognitive/cognitive_agent.py)) — NOT the decomposer — so a new `create_task` *intent descriptor* would never fire in chat. Yeo currently has 5 intents ([yeoman.py:63-110](../src/probos/cognitive/yeoman.py)), none for task creation, and overrides neither `decide()` nor `act()`.

**Recommended approach (instructions-first + reply-tag, following the `[MOVE]` precedent):**

1. **Yeo conversational instructions** — extend Yeo's conversational guidance (Yeo-scoped, not base) to teach a tag:
   `[CREATE_TASK title=... | instructions=... | specialist=@callsign]`
   "When the Captain asks you to research/produce/investigate something that is real work (not a quick answer), emit this tag in your reply. Confirm conversationally that you've opened the task and will report back."
   - Note the BF-599 seam: Yeo's static `instructions`/`_ROLE_RULES` are NOT in the conversational prompt (`compose_instructions(..., hardcoded_instructions="")`). The tag protocol must be injected the same way BF-599's `_conversational_capability_block` is — i.e. appended inside the `is_conversation` branch. Consider a sibling Yeo-overridable hook `_conversational_task_protocol(observation) -> str` (base returns `""`), appended next to `_cap_block` at [cognitive_agent.py:2224](../src/probos/cognitive/cognitive_agent.py).
2. **Reply post-processor** — in `routers/agents.py:agent_chat` (the DM reply path), after Yeo's reply is produced, parse `[CREATE_TASK ...]` (regex sibling of `_MOVE_RE` in [dm_sanity_gate.py:41](../src/probos/cognitive/dm_sanity_gate.py)). On match:
   - Resolve `specialist` callsign → agent UUID via `callsign_registry` (fallback: Yeo's existing department keyword map [yeoman.py:485](../src/probos/cognitive/yeoman.py) — "research/analyze/study" → science/Number One).
   - `await runtime.work_item_store.create_work_item(title=..., description=<instructions>, work_type="task", assigned_to=<specialist_uuid>, created_by="captain", metadata={"dispatchable": True}, tags=["yeo-delegated"])`.
   - **Strip the tag** from the Captain-visible reply (sibling of `_MOVE_STRIP_RE`), append the created task id to the confirmation.
   - Honest-degrade: if `work_item_store` is None or create fails → log warning, leave the conversational reply intact (Tier-2 log-and-degrade), no tag leak to the Captain.
3. The created item is `dispatchable` → AD-834/AD-839 engine runs the research automatically and surfaces it on the kanban board. **No new execution code.**

**Acceptance criteria.**
- New tests in `tests/test_ad845_yeo_chat_task_creation.py` (≥5, real `AgentRegistry` + real `WorkItemStore` fixture, NO MagicMock at substrate boundary — see Phantom-via-MagicMock memory): (a) tag in reply → work item created with `dispatchable=True` + `assigned_to` resolved; (b) tag stripped from Captain-visible text; (c) no-tag reply → no work item, text unchanged; (d) `work_item_store=None` → honest-degrade, reply intact, no exception; (e) unresolved specialist → falls back to keyword-mapped department, still creates item.
- Tag text must NOT contain decomposer `_CAPABILITY_GAP_RE` tokens (gap-regex-safe, BF-599 lesson).
- Verify compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Do NOT build:** the completion DM (AD-846), the desktop bridge (AD-847), a new decomposer intent, any change to `WorkItemRouter`/execution, kanban UI changes. Do not override Yeo's `decide()`/`act()`/`perceive()`.

---

## AD-846 — Task completion → proactive Yeo DM to the Captain

**Problem.** `WORK_ITEM_STATUS_CHANGED` fires on completion but nothing turns it into a Captain DM. (grep confirmed only `WORK_ITEM_CREATED` + `WORK_ITEM_STATUS_CHANGED` exist — do not assume a `WORK_ITEM_DONE` event.)

**Approach.**
- Subscribe a listener (wired in `runtime.py` startup, alongside existing event wiring) to `WORK_ITEM_STATUS_CHANGED`. Filter: new status == `WorkItemStatus.DONE` (and `FAILED`, with a different message) AND `metadata.get("dispatchable")` AND item was `tags`-marked `yeo-delegated` (so only Yeo-originated tasks notify — avoid spamming the Captain for every system work item).
- On match, have **Yeo** deliver the DM using the verified AD-485 Captain-DM pattern [proactive.py:3861-3886](../src/probos/proactive.py): find/create `dm-captain-{yeo.id[:8]}` channel → `ward_room.create_thread(...)` with the task title + a short result summary (pull from the work item's result/`metadata`/last step). This lands in **both** the 1:1 Yeo chat and the Ward Room DM inbox (same channel backs both surfaces).
- Hold the task reference (no fire-and-forget — async memory rule). Honest-degrade if `ward_room` is None.

**Acceptance criteria.**
- `tests/test_ad846_completion_dm.py` (≥4): DONE→DM created in dm-captain channel; FAILED→distinct message; non-`yeo-delegated` item→no DM; `ward_room=None`→log-and-degrade no crash.
- Verify Engineering-Principles compliance.

**Do NOT build:** desktop notification, kanban refresh, AD-845's creation path.

---

## AD-847 — Desktop OS notification on completion, click opens Yeo chat

**Problem.** Electron main only calls `notify()` on connection lifecycle events ([desktop/src/main/index.ts:296](../desktop/src/main/index.ts)) — it does not listen for work-item/DM events. The renderer (HXI) holds the runtime event stream.

**Approach (renderer → preload IPC → main `notify`):**
- Renderer already receives runtime events (incl. the new completion DM). Add a small handler: on a Yeo completion DM event, call a new preload-exposed bridge `window.probos.notifyTaskDone({ title, body, route })`.
- Add the `ipcMain.handle`/`ipcMain.on` counterpart in `desktop/src/main/index.ts` that calls `notify({title, body}, { showAndRoute })` with `route` = the Yeo 1:1 chat deep-link (reuse the existing `showAndRoute` activator already passed to `notify`).
- Expose `notifyTaskDone` through the existing `preload` contextBridge (follow the existing `probos:*` IPC channel naming).

**Acceptance criteria.**
- Vitest/desktop test (follow existing desktop test pattern): preload bridge invokes the IPC channel; main handler calls `notify` with the routed activator. (If desktop has no test harness yet, add a focused unit test around the IPC handler; do not skip per UI-test rule.)
- Verify Engineering-Principles compliance.

**Do NOT build:** new WebSocket in main (reuse the renderer's stream + IPC), AD-845/846 server code, kanban changes.

---

## Suggested sequence & gates

1. **AD-845** → focused tests green → full gate → commit → **stop, review**.
2. **AD-846** → focused tests green → full gate → commit → **stop, review**.
3. **AD-847** (desktop/UI) → `cd ui && npx vitest run` + desktop build → commit.

**Test invocation (CWD hazard):** `Set-Location -LiteralPath d:\ProbOS` then
`d:/ProbOS/.venv/Scripts/pytest.exe d:/ProbOS/tests/test_ad845_yeo_chat_task_creation.py --rootdir d:/ProbOS -q -n 0 -p no:cacheprovider`.

## Optional follow-ups (do NOT build now — forward markers)
- AD-848: kanban auto-refresh on `WORK_ITEM_STATUS_CHANGED` (live card movement).
- AD-849: in-HXI "Yeo is working on N tasks" ambient indicator.
- AD-850: let the Captain ask Yeo "what's the status of that task?" in chat (read-back from `work_item_store`).
