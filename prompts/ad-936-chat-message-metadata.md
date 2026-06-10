# AD-936 — Chat message metadata UI: per-message avatar + timestamp (Teams/Slack/Discord style)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-936.** Highest committed+pushed: AD-934 (`69e99630`).
**Mode:** Builder. Frontend only. Vitest + `npm run build`. Commit local. No push.

## Problem (Captain-reported)
The group-chat transcript should show, like Teams/Slack/Discord: (1) the **profile icon (avatar)** next to each
agent's reply, and (2) a **date/time stamp** per message, so the Captain can see who said what and when.

## Verified vs HEAD
- The transcript renders `messages` (`AgentProfileMessage[]`) at
  `ui/src/components/profile/ProfileChatTab.tsx` ~L871, each as a bubble with `msg.text` only — no avatar, no
  timestamp shown.
- **`AgentProfileMessage` ALREADY has `timestamp: number`** (`ui/src/store/types.ts:320`, set to
  `Date.now()/1000` in `useStore.ts` `addAgentMessage` ~L1245). → **Part B (timestamp) is pure render; the
  data already exists.**
- **Avatars need author identity, which the model lacks.** Group replies are added via
  `addAgentMessage(agentId, 'agent', `${callsign}: ${text}`)` (ProfileChatTab ~L646) — the *host* `agentId`
  for ALL replies, with the real author's callsign jammed into `text` as a prefix. So per-author avatars need
  the reply's `agent_id` + `callsign` threaded into the message model.
- `AgentAvatarBadge` exists (`ui/src/components/AgentAvatarBadge.tsx`): props
  `{ agentId, callsign, department?, size?: 24|32, presence? }` — department-colored circle with the
  callsign initial. **Reuse it.** (No `Glyphs.tsx` change.)
- The per-reply objects are `{agent_id, callsign, text}` (`per_agent_replies`, ProfileChatTab ~L641-646).

## Changes (frontend only, all additive/backward-compatible)

### 1. `ui/src/store/types.ts` — extend the message model (optional fields)
```typescript
export interface AgentProfileMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  text: string;
  timestamp: number;
  authorId?: string;   // AD-936: per-message author (group replies); absent => host/1:1
  callsign?: string;   // AD-936: author callsign for the avatar + name label
}
```

### 2. `ui/src/store/useStore.ts` — `addAgentMessage` carries optional author info
Extend the signature with an optional 4th param (existing ~10 call sites keep working unchanged):
```typescript
addAgentMessage: (agentId: string, role: 'user'|'agent'|'system', text: string,
                  opts?: { authorId?: string; callsign?: string }) => void;
```
In the impl (~L1237), fold `authorId`/`callsign` from `opts` into the constructed `msg`. Update the
interface declaration (~L468) too.

### 3. `ui/src/components/profile/ProfileChatTab.tsx` — thread author info + render avatar + timestamp
- **Group-reply add (~L641-646):** pass author info and DROP the inline `callsign:` text prefix (the avatar +
  name label replace it):
  ```typescript
  for (const r of replies) {
    const replyText = typeof r?.text === 'string' ? r.text : '';
    if (!replyText) continue;
    useStore.getState().addAgentMessage(agentId, 'agent', replyText,
      { authorId: typeof r?.agent_id === 'string' ? r.agent_id : undefined,
        callsign: typeof r?.callsign === 'string' ? r.callsign : undefined });
  }
  ```
- **Message bubble (~L871-905):** for `role === 'agent'`, render a small header row ABOVE the bubble text:
  `<AgentAvatarBadge agentId={msg.authorId ?? agentId} callsign={msg.callsign ?? hostCallsign} department={dept} size={24} />`
  + the callsign as a name label + a dim formatted timestamp. For `role === 'user'` (Captain) and `'system'`,
  render just a dim timestamp (no avatar). Resolve `hostCallsign`/`dept` from the store
  (`useStore(s => s.agents).get(msg.authorId ?? agentId)`), Tier-2 fallback to `''` (badge degrades to the
  default-colored initial). Keep `renderMessageBodyWithArtifacts(msg.text, threadId)` as the body.
- **Time formatter:** add a small pure helper (module-scope in ProfileChatTab, or a tiny
  `ui/src/utils/formatChatTime.ts`) `formatChatTime(tsSeconds: number): string` → local `HH:MM` (e.g.
  `new Date(ts*1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})`). Date-grouping headers
  ("Today"/date separators) are forward marker **AD-936a** — v1 is time-only.
- **HXI compliance:** no emoji; the avatar is the existing stroke/initials badge; timestamp dim
  (`#666680`-ish), small (`fontSize: 10-11`). Avatar + name + time sit in a fl/`display:flex` header row,
  left-aligned for agent messages (matching the existing `textAlign:left`).

## Tests — Vitest, floor +8 (+`npm run build` clean)
New `ui/src/components/profile/__tests__/ProfileChatTab.metadata.test.tsx` (mirror the existing
`ProfileChatTab.*` test idioms; real store via `useStore.setState`, BF-287). If full-`ProfileChatTab` render
is too heavy (the `groupsend`/`bf294b` precedent), test a small extracted presentational
`ChatMessageRow` component instead — prefer extracting `ChatMessageRow({ msg, hostAgentId, hostCallsign })`
and testing IT, which also keeps the bubble JSX tidy.
1. An `agent` message renders an `AgentAvatarBadge` (assert testid/initial) + the callsign label + a
   formatted `HH:MM` timestamp.
2. Two group replies from DIFFERENT authors render TWO distinct avatars (different `agentId`/initial).
3. A message with no `authorId` (1:1 / legacy) falls back to the host agent's avatar — no crash.
4. A `user` (Captain) message renders a timestamp and NO avatar.
5. A `system` message renders unchanged (no avatar; existing dim-italic style preserved).
6. `formatChatTime` formats a known epoch to the expected `HH:MM` (use a fixed timestamp; assert the
   `toLocaleTimeString` shape, locale-agnostic — assert it matches `/\d{1,2}:\d{2}/`).
7. `addAgentMessage` without `opts` still constructs a valid message (backward compatibility); with `opts`
   the `authorId`/`callsign` land on the stored message.
8. No-emoji guard (`/\p{Extended_Pictographic}/u`) on the rendered container / `?raw` source.

## Gates
- `cd d:\ProbOS\ui; npx vitest run` (full suite — report pass/skip counts vs the AD-934 baseline 1376-era UI
  count; confirm zero regressions).
- `cd d:\ProbOS\ui; npm run build` (tsc -b + vite) — must be clean.
- No backend change → no pytest.

## Acceptance
- Every agent message shows the author's avatar + callsign + `HH:MM`; group replies show DISTINCT per-author
  avatars; Captain/system messages show a timestamp (no avatar); 1:1 falls back to the host avatar.
- Backward-compatible: the new message fields + `addAgentMessage` param are optional; existing call sites and
  tests unaffected. `npm run build` clean. Verify Engineering-Principles compliance.

## Do NOT
- No backend / REST / pytest. No new WebSocket or poll (live-refresh is AD-935a / a separate AD). No
  `Glyphs.tsx` change. No `AgentAvatarBadge` API change (reuse as-is). No date-separator headers (AD-936a).
- Do NOT touch the AD-935 cascade, the fan-out, `DmReplyPipeline`, or the Ward Room.
- No push. Stage explicit paths (NOT `git add -A`); deletion-audit before commit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-936 row, SHIPPED + 2026-06-08 + gate note.
- `PROGRESS.md`: prepend an AD-936 block.
- `DECISIONS.md` (match where AD-934 went): AD-936 entry — per-message avatar (model extended with optional
  author identity, group replies thread `agent_id`/`callsign`, reuse `AgentAvatarBadge`) + timestamp (data
  already on the model), `ChatMessageRow` extraction, forward marker AD-936a (date-separator headers).
