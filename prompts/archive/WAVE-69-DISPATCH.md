# WAVE 69 DISPATCH — AD-574b v1 Synchronous DM Reply (Combo Reframe 2→1)

**Wave id:** 69
**Single AD:** AD-574b (last buildable child of the AD-574b-c combo)
**Closes (partial):** GH issue #110 — one child shipping this wave, one wholesale-deferred to AD-574c-i
**Baseline test count:** 11411 (HEAD `09971a6`, post-Wave-68) → expected **11419** (+8 net pytest), window **[+6, +10]**. Vitest UI gate adds **+6** independently (not counted in pytest gate).
**HEAD at draft:** `09971a6`, working tree clean
**Builder:** required

## Reframe Summary (Wave-10 pattern at AD scoping, third consecutive instance: 2→1)

Wave 69 was queued as a 2-AD combo (AD-574b + AD-574c) per `prompts/wave-plan.yaml` id=69. The Wave 68 dispatch (`prompts/archive/WAVE-68-DISPATCH.md` DLog #8) explicitly named Wave 69 as a future verify-first target, on the precedent of Wave 67 (5→1) and Wave 68 (4→0). Verify-first against HEAD `09971a6` confirms:

| Child | Outstanding? | Source-of-truth |
|---|---|---|
| **AD-574b** | ✅ YES — buildable this wave | `ui/src/components/wardroom/WardRoomThreadDetail.tsx:35-50` `submitReply` posts to `/api/wardroom/threads/{id}/posts` (async only); zero call sites of `/api/agent/{id}/chat` from ward room components; no "thinking" indicator state in `useStore.ts` |
| **AD-574c** | ❌ NO — wholesale-deferred to AD-574c-i | hard forcing function: `agentConversations: Map<string, AgentConversation>` at `useStore.ts:242` and `wardRoomThreadDetail` at `:250` are two stores with different shapes (`AgentConversation.messages` is `{role, text}` vs `WardRoomPost` carries `id, author_id, parent_post_id, body, created_at, children, net_score`). Convergence requires deciding the canonical record shape AND migrating ProfileChatTab's `/api/agent/{id}/chat/history` reader (`ProfileChatTab.tsx:24`) to read from a Ward Room DM thread. AD-574b establishes Ward Room as the canonical write surface for DM via dual-write — that is the forcing function for AD-574c-i (which then refactors ProfileChatTab to read from `/api/wardroom/dms/{channel_id}/threads` + `/api/wardroom/threads/{id}` instead of `agentConversations`). |

**Reframe verdict: ship AD-574b alone. Partially close #110** with a summary noting (1 shipped + 1 deferred-with-forcing-function). Same Wave-10 architectural-honesty-over-scope pattern Wave 67 applied 5→1 and Wave 68 applied 4→0; Wave 69 takes it 2→1 because AD-574c's data-store unification needs AD-574b's dual-write path live first before the ProfileChatTab reader can be safely swapped.

## Summary

The Captain's DM panel (Ward Room view `dm-detail`) is currently asymmetric with `ProfileChatTab`:

- `ProfileChatTab.tsx:52` calls `POST /api/agent/{id}/chat` synchronously, sets `sending=true`, awaits the agent's response, and renders both messages immediately. Responsive UX.
- `WardRoomThreadDetail.tsx:35-50` `submitReply` posts to `/api/wardroom/threads/{id}/posts` and clears the input. The agent does NOT respond inline — it responds on the next proactive cycle (because AD-574 wired Captain-in-DM into `WardRoomRouter.find_targets`). The Captain types, and an empty thread sits there for ~30s before a reply appears.

AD-574b v1 closes the gap by making `WardRoomThreadDetail.submitReply` route through `/api/agent/{id}/chat` when the thread is a DM (`view === 'dm-detail'`), display a "thinking…" placeholder while the request is in flight, and **dual-write** both the Captain's message and the agent's response back into the Ward Room thread for record-keeping. The proactive cycle's ambient response path stays intact; the only change is the synchronous foreground path now beats the proactive cycle to the post.

**Backend support (AD-574b)** — extend `GET /api/wardroom/dms` and `GET /api/wardroom/captain-dms` to include a `target_agent_id` field for each DM channel, computed by resolving the channel-name participant prefix against `runtime.registry.all()`. The UI needs the full agent_id (not the 8-char prefix) to call `/api/agent/{id}/chat`. Channel name format is documented at `ward_room/channels.py:203` (`dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}`) and at `proactive.py:3599` (`dm-captain-{agent.id[:8]}`).

**No service-side change** to `WardRoomThreadDetail`'s rendering path beyond the new submit branch; existing `WardRoomPostItem` tree continues to render. **No new Pydantic config.** **No new module.** **No new public attribute on runtime.** **No new EventType.** **No change to `/api/agent/{id}/chat`** (already exists, already crew-only-gated).

**Deferred at the prompt level:**
- AD-574b-1 — streaming "thinking…" indicator with periodic LLM-thought updates. v1 ships a static placeholder; streaming requires SSE/WebSocket on `/api/agent/{id}/chat`, which is a separate endpoint contract change.
- AD-574b-2 — Captain typing-indicator surface to the agent (so the agent's working memory knows the Captain is mid-message). Not in scope; the existing direct_message intent is fire-and-forget.
- AD-574b-3 — *(Commercial)* multi-Captain coordination (per-Captain DM channels, presence). The OSS dual-write surface stays single-Captain.

**Wholesale-deferred to AD-574c-i:**
- AD-574c (DM conversation convergence) — unify `ProfileChatTab.agentConversations` Map with Ward Room DM threads. Forcing function: AD-574b dual-write must be live so that any DM exchange has a Ward Room record; AD-574c-i then refactors ProfileChatTab to read from `/api/wardroom/dms/{channel_id}/threads` + `/api/wardroom/threads/{id}` (via the same channel naming convention AD-574b uses to find the channel from `agentId`) and removes the standalone `agentConversations` map. Cannot land in Wave 69 because the dual-write seam (AD-574b) must exist first; doing it inline would conflate two architectural changes (foreground sync UX + canonical-store swap) into one prompt.

## Architect calls (Decision Log)

- **DLog #1 — `target_agent_id` on the DM listing API, not channel-name parsing in the UI.** The UI code currently has zero knowledge of channel-name format. Pushing prefix-extraction into TypeScript would couple frontend to a backend convention that has already mutated once (the `dm-captain-{prefix}` form at `proactive.py:3599` differs from the sorted `dm-{a}-{b}` form at `ward_room/channels.py:203`). Resolution at the API layer (using `runtime.registry.all()`) is one ~12-line helper in `routers/wardroom.py` and keeps the format private.

- **DLog #2 — Dual-write client-side, not server-side.** The `/api/agent/{id}/chat` endpoint stays unchanged. After the chat call returns, the UI posts both `{author_id: 'captain', body: <user message>}` and `{author_id: <agent_id>, body: <response>}` to `/api/wardroom/threads/{thread_id}/posts`. Server-side dual-write would require `/api/agent/{id}/chat` to know which Ward Room thread to write into, which is a UI-state concern (the DM panel knows; the chat endpoint does not). Client-side dual-write keeps the chat endpoint context-free and reusable by ProfileChatTab.

- **DLog #3 — `target_agent_id` is `null` when the participant cannot be resolved.** If the channel name encodes a prefix that no longer matches any live agent (deleted agent, renamed agent), the backend returns `null` rather than raising. Frontend treats `null` as "fall back to the existing async post path" — graceful degradation. Tier-2 log-and-degrade per the Engineering Principles.

- **DLog #4 — "Thinking" placeholder lives in `useStore`, not as a component-local boolean.** `WardRoomThreadDetail` already reads from the store via `useStore(s => s.wardRoomThreadDetail)`; adding a `wardRoomDmPending: { threadId: string, captainText: string } | null` slice keeps the placeholder inline with the canonical store and survives re-mounts (e.g., panel reorder during the in-flight request). When the chat call resolves, the slice clears and the dual-write posts replace the placeholder via the existing `selectWardRoomThread` refresh path.

- **DLog #5 — No change to the proactive ambient-response path.** AD-574 wired Captain-in-DM into `WardRoomRouter.find_targets` at `ward_room_router.py:841-851` so that the agent eventually notices the unread DM on its next think cycle. AD-574b does NOT remove that path. If the synchronous `/api/agent/{id}/chat` succeeds, the dual-write posts mark the thread as "agent has authored", which is the same condition that suppresses the proactive notification (per the AD-574 unread query rewrite — last author is not the agent). If the synchronous chat call fails (timeout, error), the user message still posts via the fallback async path AND the proactive cycle still sees the unread Captain post. Belt-and-suspenders by design.

- **DLog #6 — Crew-only gate is enforced by the existing endpoint.** `routers/agents.py:174-176` raises `HTTPException(400)` for non-crew agents. The UI's "thinking" placeholder must show an error when this raises. v1 displays the existing `(communication error)` style fallback inline.

- **DLog #7 — Vitest tests required for the UI changes.** Per the HXI test requirement in `.github/copilot-instructions.md` ("Every UI change … must include a Vitest component test. The HXI has broken from untested UI changes multiple times — tooltips, bloom position, chat rendering. No UI PR without tests."). The new `WardRoomThreadDetail` submit branch and the `wardRoomDmPending` store slice both need Vitest coverage. Existing `ui/src/__tests__/WardRoomPostItem.test.tsx` and `WardRoomPanel.test.tsx` are precedents for component-level tests with mocked `useStore`.

- **DLog #8 — Backend test for `target_agent_id` field.** `routers/wardroom.py` `list_dm_channels` at `:26` and `list_captain_dms` at `:65` both gain the new field. Test added at `tests/test_ward_room_dms.py` adjacent to the existing `TestDmApi` class — extends the pattern used by `test_dm_api_list_dm_channels` at `:158`.

- **DLog #9 — Wave-10 reframe APPLIED at AD-scoping, third consecutive instance.** Wave 67 reframed 5→1 on AD-573 family, Wave 68 reframed 4→0 on AD-572 family, Wave 69 reframes 2→1 on AD-574 family. The pattern is now systemic on combo waves whose parent ADs were partial-closed in earlier waves. The session memory tracker `/memories/session/wave-queue-resume.md` (authored 2026-04-06) is the staleness source for all three; refreshing it post-Wave-69 is a Captain hygiene task. The remaining queued combo (Wave 70 / id=70 AD-526c-h on issue #101) MUST verify-first the same way before its dispatch is drafted.

- **DLog #10 — Commercial-leak audit: clean.** Wave 69 ships:
  - One UI submit-branch change in `WardRoomThreadDetail.tsx`.
  - One store slice add (`wardRoomDmPending`) in `useStore.ts` + `types.ts`.
  - One backend field add (`target_agent_id`) on two DM listing endpoints in `routers/wardroom.py`.
  - One participant-resolution helper (private) on `routers/wardroom.py`.
  - Six Vitest tests + four pytest tests + one DECISIONS.md entry.

  Zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, GTM language. The single `*(Commercial)*` AD-574b-3 deferral entry contains only the seam description ("multi-Captain coordination — the OSS dual-write surface stays single-Captain"), not pricing or tiering. Verified clean against the boundary rule from `.github/copilot-instructions.md` ("Repository Boundary — OSS vs Commercial").

- **DLog #11 — Phantom-API pre-check.** Run `scripts/phantom-api-precheck.ps1` against `prompts/ad-574b-dm-sync-chat.md`. Expected FPs: 1× `target_agent_id` field (intra-prompt-introduction on the dict response shape — same FP class as Waves 27-68); 1× `wardRoomDmPending` (TypeScript identifier, helper does not parse `.tsx`/`.ts` so noop); 0 NEW phantoms expected. If a NEW phantom appears, hard-stop and surface to the architect.

## Captain workflow (Builder required)

1. **Pre-flight verification.** Run `pytest tests/ -q -n 4 --dist=loadfile` and confirm 11411 collected at HEAD `09971a6`. If the count drifts, investigate baseline rot before proceeding (the rot is not from Wave 69).

2. **Run phantom-API pre-check** on the per-AD prompt: `scripts/phantom-api-precheck.ps1 prompts/ad-574b-dm-sync-chat.md`. Confirm only the two expected FPs above; halt on any NEW phantom.

3. **Dispatch the Builder** against `prompts/ad-574b-dm-sync-chat.md`. The Builder will:
   - Edit `src/probos/routers/wardroom.py` (add `_resolve_dm_target_agent_id` helper + `target_agent_id` field on `list_dm_channels` and `list_captain_dms`).
   - Edit `ui/src/store/types.ts` (add `wardRoomDmPending` type).
   - Edit `ui/src/store/useStore.ts` (add `wardRoomDmPending` slice + setter).
   - Edit `ui/src/components/wardroom/WardRoomThreadDetail.tsx` (`submitReply` branches on DM view + sync chat call + dual-write + placeholder).
   - Add `tests/test_ad574b_dm_sync_chat.py` (8 pytest tests for `_resolve_dm_target_agent_id`).
   - Add `ui/src/__tests__/WardRoomDmSync.test.tsx` (6 Vitest tests for UI submit branch + placeholder).
   - Add a DECISIONS.md AD-574b entry.

4. **Run focused gate** after Builder's commit: `pytest tests/test_ad574b_dm_sync_chat.py tests/test_ward_room_dms.py -v -n 0` AND `cd ui && npx vitest run --reporter=basic` (Vitest may need `WardRoomDmSync.test.tsx` only). Both must pass before the full gate.

5. **Run full gate**: `pytest tests/ -q -n 4 --dist=loadfile`. Expected delta: **+8 pytest** (window [+6, +10]), total **11419**. Vitest gate (`cd ui && npx vitest run`) is independent and adds +6 UI tests.

6. **Update `prompts/wave-plan.yaml`** entry id=69 to `status: done`, replace `prompts_already_drafted: false` with `true`, keep `prompt_paths: ["prompts/ad-574b-dm-sync-chat.md"]`, and append a `notes:` block:

   ```yaml
     - id: "69"
       title: "AD-574b-c Combo DM Reply Extensions (sync chat ships, convergence deferred)"
       kind: combo
       depends_on: ["68"]
       dispatch_prompt: "prompts/WAVE-69-DISPATCH.md"
       prompts_already_drafted: true
       prompt_paths:
         - "prompts/ad-574b-dm-sync-chat.md"
       builder_required: true
       issues_to_close: [110]
       status: done
       notes: |
         Wave-10 reframe applied at AD scoping (2→1). At HEAD 09971a6:
           - AD-574b shipped this wave (Builder-driven; client-side dual-write
             routes Captain DM through /api/agent/{id}/chat with thinking
             indicator; backend gains target_agent_id on DM listing endpoints).
           - AD-574c wholesale-deferred to AD-574c-i (forcing function:
             AD-574b establishes Ward Room as canonical DM write surface;
             AD-574c-i then refactors ProfileChatTab to read from
             /api/wardroom/dms instead of standalone agentConversations Map).
         Issue #110 closes via partial-completion summary in the close comment.
   ```

7. **Append to `PROGRESS.md`** a CLOSED paragraph in the Wave 67/68 close shape. Suggested text:

   > **Wave 69 (AD-574b v1 Synchronous DM Reply): CLOSED.** AD-574b shipped — `WardRoomThreadDetail.submitReply` now branches on `view === 'dm-detail'`, calls `/api/agent/{id}/chat` synchronously, displays a "thinking…" placeholder via the new `wardRoomDmPending` store slice, then dual-writes both Captain message and agent response back into the Ward Room thread for record-keeping. Backend `/api/wardroom/dms` and `/api/wardroom/captain-dms` gain `target_agent_id` field via `_resolve_dm_target_agent_id` helper. AD-574c wholesale-deferred to AD-574c-i (forcing function: AD-574b dual-write must be live before ProfileChatTab data-source swap; cannot conflate two architectural changes into one prompt). Issue #110 closed with partial-completion summary (1 shipped + 1 deferred-with-forcing-function). 8 pytest + 6 Vitest tests added; pytest full gate **11419** passing.

8. **Commit and push** the Builder commit + the wave-plan/PROGRESS edits per the standard workflow.

9. **Archive this dispatch:**

   ```
   git mv prompts/WAVE-69-DISPATCH.md prompts/archive/WAVE-69-DISPATCH.md
   git mv prompts/ad-574b-dm-sync-chat.md prompts/archive/ad-574b-dm-sync-chat.md
   git add -A
   git commit -m "Wave 69 archive: AD-574b sync DM (#110)"
   git push
   ```

10. **Close GH issue #110** with:

    > Closed by Wave 69 (2→1 reframe). AD-574b shipped <commit>. AD-574c wholesale-deferred to AD-574c-i (forcing function documented in wave-plan.yaml id=69 notes and DECISIONS.md AD-574b entry). 1 of 2 children shipped; partial close.

## Verified Against Codebase (2026-05-05, HEAD 09971a6)

```
grep -n "AD-574" decisions-era-4-evolution.md DECISIONS.md PROGRESS.md
  decisions-era-4-evolution.md:2888: ### AD-574: DM Reply Agent Notification
  PROGRESS.md:363: AD-574 COMPLETE (DM Reply Agent Notification — ...)

grep -n "AD-574b\|AD-574c" docs/development/roadmap.md
  4606: **Deferred:** AD-574b (synchronous DM response in HXI — `/api/agent/{id}/chat` from DM panel with "agent is thinking..." indicator), AD-574c (DM conversation convergence — unify ProfileChatTab and Ward Room DM into single conversation store).

grep -n "submitReply\|/api/wardroom/threads" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  35:  const submitReply = async () => {
  38:      await fetch(`/api/wardroom/threads/${activeThread}/posts`, {

grep -n "/api/agent.*chat" ui/src/components/profile/ProfileChatTab.tsx
  24:    fetch(`/api/agent/${agentId}/chat/history`)
  52:      const res = await fetch(`/api/agent/${agentId}/chat`, {

grep -n "/api/wardroom/dms\|list_dm_channels\|list_captain_dms" src/probos/routers/wardroom.py
  26: @router.get("/dms")
  27: async def list_dm_channels(runtime: Any = Depends(get_runtime)):
  64: @router.get("/captain-dms")
  65: async def list_captain_dms(runtime: Any = Depends(get_runtime)):

grep -n "agent_chat\|/{agent_id}/chat" src/probos/routers/agents.py
  166: @router.post("/{agent_id}/chat")
  167: async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:

grep -n "channel_name = f\"dm-\|dm-captain-" src/probos/ward_room/channels.py src/probos/proactive.py
  ward_room/channels.py:203:    channel_name = f"dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}"
  proactive.py:3599: captain_channel_name = f"dm-captain-{agent.id[:8]}"

grep -n "agentConversations\|wardRoomThreadDetail\|wardRoomView" ui/src/store/useStore.ts
  242:  agentConversations: Map<string, AgentConversation>;
  250:  wardRoomThreadDetail: { thread: WardRoomThread; posts: WardRoomPost[] } | null;
  252:  wardRoomView: 'channels' | 'dms' | 'dm-detail';

grep -n "channel_type.*=.*\"dm\"\|find_targets" src/probos/ward_room_router.py
  841: elif channel.channel_type == "dm":
  843: # AD-574: DM channel — notify the other participant (no EA gating)
  851: agent.id[:8] in channel.name):

grep -n "captain_post_in_dm" tests/test_ward_room_agents.py
  585: async def test_captain_post_in_dm_notifies_agent(self):
```

Each concrete claim in the dispatch and the per-AD prompt maps to one of the above grep hits.
