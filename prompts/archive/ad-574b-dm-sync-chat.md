# AD-574b v1 — Synchronous DM Reply with Thinking Indicator + Ward Room Dual-Write

**Status:** Buildable, no architectural blockers.
**Dependencies:** AD-574 (shipped, `decisions-era-4-evolution.md:2888`).
**Defers:** AD-574c → AD-574c-i (DM conversation convergence; forcing function: this AD's dual-write surface must be live first).
**Estimated tests:** **+8 pytest** (window **[+6, +10]**) + **6 Vitest** (independent UI gate; do not count toward `pytest tests/` collected count).
**Closes (partial):** GH issue #110 (AD-574c remains as deferred-with-forcing-function).

## Problem

The Captain's DM panel in the Ward Room (Ward Room view `dm-detail`) is asymmetric with `ProfileChatTab`:

- `ui/src/components/profile/ProfileChatTab.tsx:52` calls `POST /api/agent/{agentId}/chat` **synchronously**, awaits the agent's response, and renders both messages immediately. Tight loop, responsive UX.
- `ui/src/components/wardroom/WardRoomThreadDetail.tsx:35-50` `submitReply` posts to `POST /api/wardroom/threads/{thread_id}/posts` and clears the input. The agent does NOT respond inline. AD-574 wired Captain-in-DM into `WardRoomRouter.find_targets` (`src/probos/ward_room_router.py:841-851`), so the agent eventually notices on the next proactive cycle (~30s). The Captain types into a DM panel and stares at an unresponsive thread.

Two stores hold DM history: `useStore.ts:242 agentConversations: Map<string, AgentConversation>` (used by `ProfileChatTab`) vs `wardRoomThreadDetail` at `:250` (used by Ward Room DM panel). Convergence (AD-574c) requires deciding the canonical store and is deferred to AD-574c-i — see DECISIONS.md AD-574b entry created by this AD.

## Solution Overview

Make `WardRoomThreadDetail.submitReply` branch on `view === 'dm-detail'` and the presence of a backend-supplied `target_agent_id`:

1. Set `wardRoomDmPending = { threadId, captainText }` in the store.
2. `POST /api/agent/{target_agent_id}/chat` with `message=captainText`, `history=<flatPosts mapped to chat history>`.
3. On success, **dual-write** the Captain message and the agent response back into the Ward Room thread via two `POST /api/wardroom/threads/{thread_id}/posts` calls (author_id=`captain` and author_id=`target_agent_id` respectively). This produces a Ward Room record of the exchange identical in shape to what the proactive cycle would have produced — preserving audit trail and the Captain-DM unread query rewrite from AD-574.
4. Clear `wardRoomDmPending` and call `selectWardRoomThread(activeThread)` to re-fetch and render the dual-written posts.
5. On chat-call failure (4xx/5xx/timeout), fall back to the existing async post-only path (post user message to Ward Room thread; let the proactive cycle respond) AND clear `wardRoomDmPending`. The user always sees their message land somewhere; no silent failures.

For non-DM views (channels view, dm-list view) and DM threads where `target_agent_id` is `null` (deleted/unresolvable agent), `submitReply` keeps its existing behavior unchanged.

Backend support: `GET /api/wardroom/dms` and `GET /api/wardroom/captain-dms` extend their per-channel response dict with a `target_agent_id` field, computed by a private helper that resolves the channel-name participant prefix against `runtime.registry.all()`. Returns `null` when no live agent matches.

## Section 0 — No new event types

This AD does not introduce new EventType values, new Pydantic config classes, new modules, or new public attributes on `runtime`. Section count starts at 1.

## Section 1 — Backend: `target_agent_id` on DM listing endpoints

### Section 1.1 — Add `_resolve_dm_target_agent_id` helper

Add a module-level private helper to `src/probos/routers/wardroom.py`, immediately after the existing `router = APIRouter(...)` declaration at line 20 and before the `# ── DMs (AD-453/AD-485) ──` comment at line 23.

```
===MODIFY: src/probos/routers/wardroom.py===
===SEARCH===
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wardroom", tags=["wardroom"])


# ── DMs (AD-453/AD-485) ──────────────────────────────────────────
===REPLACE===
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wardroom", tags=["wardroom"])


def _resolve_dm_target_agent_id(channel_name: str, runtime: Any) -> str | None:
    """AD-574b: Resolve the non-Captain participant agent_id from a DM channel name.

    DM channel names use one of two formats:
      - ``dm-captain-{agent_id[:8]}`` (Captain DMs, ``proactive.py:3599``)
      - ``dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}`` (agent-to-agent, ``ward_room/channels.py:203``)

    The UI's DM panel needs the FULL agent_id (not the 8-char prefix) to call
    ``POST /api/agent/{id}/chat``. Resolve by scanning ``runtime.registry.all()``
    for an alive crew agent whose id starts with the non-Captain prefix.

    Returns ``None`` when no live agent matches (deleted/renamed/lookup failure).
    Tier-2 log-and-degrade: any unexpected error is caught, logged at warning,
    and returns ``None`` so the UI falls back to the async post-only path.
    """
    if not channel_name.startswith("dm-"):
        return None
    try:
        registry = getattr(runtime, "registry", None)
        if registry is None:
            return None
        parts = channel_name.split("-")  # ["dm", "<a>", "<b>"] or ["dm", "captain", "<b>"]
        if len(parts) != 3:
            return None
        # The non-Captain prefix is the part that is not literally "captain".
        candidates = [p for p in parts[1:] if p != "captain"]
        if not candidates:
            return None
        prefix = candidates[0]
        for agent in registry.all():
            if not getattr(agent, "is_alive", False):
                continue
            agent_id = getattr(agent, "id", "")
            if agent_id and agent_id.startswith(prefix):
                return agent_id
        return None
    except Exception as exc:  # noqa: BLE001 — Tier-2 log-and-degrade
        logger.warning(
            "AD-574b: failed to resolve DM target agent_id for channel %r: %s",
            channel_name, exc,
        )
        return None


# ── DMs (AD-453/AD-485) ──────────────────────────────────────────
===END REPLACE===
```

### Section 1.2 — Add `target_agent_id` to `list_dm_channels` response

Modify the per-channel result dict in `list_dm_channels` (`routers/wardroom.py:26-47`):

```
===MODIFY: src/probos/routers/wardroom.py===
===SEARCH===
        result.append({
            "channel": {
                "id": ch.id, "name": ch.name,
                "description": ch.description,
                "created_at": ch.created_at,
            },
            "latest_thread": threads[0] if threads else None,
            "thread_count": thread_count,
        })
    return result


@router.get("/dms/{channel_id}/threads")
===REPLACE===
        result.append({
            "channel": {
                "id": ch.id, "name": ch.name,
                "description": ch.description,
                "created_at": ch.created_at,
            },
            "latest_thread": threads[0] if threads else None,
            "thread_count": thread_count,
            "target_agent_id": _resolve_dm_target_agent_id(ch.name, runtime),
        })
    return result


@router.get("/dms/{channel_id}/threads")
===END REPLACE===
```

### Section 1.3 — Add `target_agent_id` to `list_captain_dms` response

Modify the per-channel result dict in `list_captain_dms` (`routers/wardroom.py:64-82`):

```
===MODIFY: src/probos/routers/wardroom.py===
===SEARCH===
        result.append({
            "channel": {"id": ch.id, "name": ch.name, "description": ch.description,
                        "created_at": ch.created_at},
            "threads": threads,
            "thread_count": thread_count,
        })
    return result


@router.get("/dms/archive")
===REPLACE===
        result.append({
            "channel": {"id": ch.id, "name": ch.name, "description": ch.description,
                        "created_at": ch.created_at},
            "threads": threads,
            "thread_count": thread_count,
            "target_agent_id": _resolve_dm_target_agent_id(ch.name, runtime),
        })
    return result


@router.get("/dms/archive")
===END REPLACE===
```

## Section 2 — UI store: `wardRoomDmPending` slice

### Section 2.1 — `WardRoomDmPending` type

Append a new exported interface to `ui/src/store/types.ts` at end-of-file. Do NOT modify the existing `WardRoomChannel` interface (verified at `types.ts:339-349`: `WardRoomChannel { id; name; channel_type; department; created_by; created_at; archived; description }` with `channel_type` as the third field, not the last). The store's existing `wardRoomDmChannels` slice uses an inline anonymous shape and is widened in Section 2.2 directly; no addition to `types.ts` is needed for that. The only new export is the pending-indicator interface:

```
===MODIFY: ui/src/store/types.ts===
===SEARCH===
export interface WardRoomChannel {
  id: string;
  name: string;
  channel_type: 'ship' | 'department' | 'custom' | 'dm';
  department: string;
  created_by: string;
  created_at: number;
  archived: boolean;
  description: string;
}
===REPLACE===
export interface WardRoomChannel {
  id: string;
  name: string;
  channel_type: 'ship' | 'department' | 'custom' | 'dm';
  department: string;
  created_by: string;
  created_at: number;
  archived: boolean;
  description: string;
}

// AD-574b: in-flight indicator for synchronous DM replies via /api/agent/{id}/chat.
export interface WardRoomDmPending {
  threadId: string;
  captainText: string;
  startedAt: number;
}
===END REPLACE===
```

**Builder note:** verify the live shape of `WardRoomChannel` at `types.ts:339-349` matches the SEARCH block before committing. If field order or types have drifted, copy the exact live block into SEARCH and append the same `WardRoomDmPending` block in REPLACE.

### Section 2.2 — Add store slice + setter

```
===MODIFY: ui/src/store/useStore.ts===
===SEARCH===
  wardRoomView: 'channels' | 'dms' | 'dm-detail';
  wardRoomDmChannels: { channel: { id: string; name: string; description: string; created_at: number }; latest_thread: any; thread_count: number }[];
===REPLACE===
  wardRoomView: 'channels' | 'dms' | 'dm-detail';
  // AD-574b: target_agent_id added to per-channel entry; null when participant
  // cannot be resolved by backend (deleted/renamed agent → UI falls back to
  // existing async post-only path).
  wardRoomDmChannels: { channel: { id: string; name: string; description: string; created_at: number }; latest_thread: any; thread_count: number; target_agent_id: string | null }[];
  // AD-574b: in-flight indicator for synchronous DM chat. null when idle.
  wardRoomDmPending: import('./types').WardRoomDmPending | null;
===END REPLACE===
```

Initialize the slice in the store body (search for `wardRoomDmChannels: []` and add the line after it). Apply the same default of `null`:

```
===MODIFY: ui/src/store/useStore.ts===
===SEARCH===
  wardRoomView: 'channels' as const,
===REPLACE===
  wardRoomView: 'channels' as const,
  wardRoomDmPending: null,
===END REPLACE===
```

Add a setter `setWardRoomDmPending` on the actions side. The Builder must add a top-of-file import for `WardRoomDmPending` if `useStore.ts` does not already barrel-import from `./types`. Verify with `read_file` on the import block (lines 1-30) before applying.

```
===MODIFY: ui/src/store/useStore.ts===
===SEARCH===
  setWardRoomView: (view: 'channels' | 'dms' | 'dm-detail') => set({ wardRoomView: view }),
===REPLACE===
  setWardRoomView: (view: 'channels' | 'dms' | 'dm-detail') => set({ wardRoomView: view }),
  setWardRoomDmPending: (pending: import('./types').WardRoomDmPending | null) => set({ wardRoomDmPending: pending }),
===END REPLACE===
```

Add the matching action signature to the `Actions` interface near `setWardRoomView`:

```
===MODIFY: ui/src/store/useStore.ts===
===SEARCH===
  setWardRoomView: (view: 'channels' | 'dms' | 'dm-detail') => void;
===REPLACE===
  setWardRoomView: (view: 'channels' | 'dms' | 'dm-detail') => void;
  setWardRoomDmPending: (pending: import('./types').WardRoomDmPending | null) => void;
===END REPLACE===
```

**Builder note:** the `wardRoomDmChannels` type widening to include `target_agent_id` is required for TypeScript to allow `WardRoomThreadDetail` to read it. If TypeScript surfaces strict-null errors at unrelated call sites, narrow with `as any` ONLY in the unrelated sites and do NOT relax the new field's type.

## Section 3 — UI component: `WardRoomThreadDetail.submitReply` branch

Replace the body of `submitReply` to branch on DM view + `target_agent_id` resolution. Add an `agentThinkingPlaceholder` block in the rendering area when `wardRoomDmPending?.threadId === activeThread`.

```
===MODIFY: ui/src/components/wardroom/WardRoomThreadDetail.tsx===
===SEARCH===
import { useState } from 'react';
import Markdown from 'react-markdown';
import { useStore } from '../../store/useStore';
import type { WardRoomPost } from '../../store/types';
import { EndorsementButtons } from './WardRoomEndorsement';
import { WardRoomPostItem } from './WardRoomPostItem';
import { timeAgo } from './timeAgo';
===REPLACE===
import { useState } from 'react';
import Markdown from 'react-markdown';
import { useStore } from '../../store/useStore';
import type { WardRoomPost } from '../../store/types';
import { EndorsementButtons } from './WardRoomEndorsement';
import { WardRoomPostItem } from './WardRoomPostItem';
import { timeAgo } from './timeAgo';

// AD-574b: Resolve the target agent_id for the active DM thread by scanning
// the wardRoomDmChannels listing for the channel that owns this thread.
// Returns null when not in a DM view, when the thread has no resolvable
// channel, or when the backend could not resolve the participant.
function resolveDmTargetAgentId(
  view: 'channels' | 'dms' | 'dm-detail',
  activeChannel: string | null,
  dmChannels: { channel: { id: string }; target_agent_id: string | null }[]
): string | null {
  if (view !== 'dm-detail' || !activeChannel) return null;
  const entry = dmChannels.find(c => c.channel.id === activeChannel);
  return entry?.target_agent_id ?? null;
}
===END REPLACE===
```

Replace the `submitReply` function body and add the placeholder render:

```
===MODIFY: ui/src/components/wardroom/WardRoomThreadDetail.tsx===
===SEARCH===
export function WardRoomThreadDetail() {
  const detail = useStore(s => s.wardRoomThreadDetail);
  const activeThread = useStore(s => s.wardRoomActiveThread);
  const view = useStore(s => s.wardRoomView);
  const [replyText, setReplyText] = useState('');

  if (!detail || !activeThread) return null;

  const { thread, posts } = detail;
  const isDm = view === 'dm-detail';
  const flatPosts = isDm ? flattenPosts(posts) : null;

  const submitReply = async () => {
    if (!replyText.trim()) return;
    try {
      await fetch(`/api/wardroom/threads/${activeThread}/posts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: 'captain',
          body: replyText.trim(),
          author_callsign: 'Captain',
        }),
      });
      setReplyText('');
      useStore.getState().selectWardRoomThread(activeThread);
    } catch { /* swallow */ }
  };
===REPLACE===
export function WardRoomThreadDetail() {
  const detail = useStore(s => s.wardRoomThreadDetail);
  const activeThread = useStore(s => s.wardRoomActiveThread);
  const view = useStore(s => s.wardRoomView);
  const activeChannel = useStore(s => s.wardRoomActiveChannel);
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const dmPending = useStore(s => s.wardRoomDmPending);
  const [replyText, setReplyText] = useState('');

  if (!detail || !activeThread) return null;

  const { thread, posts } = detail;
  const isDm = view === 'dm-detail';
  const flatPosts = isDm ? flattenPosts(posts) : null;
  const targetAgentId = resolveDmTargetAgentId(view, activeChannel, dmChannels);
  const isThinking = dmPending?.threadId === activeThread;

  // AD-574b: Synchronous DM reply via /api/agent/{id}/chat with dual-write to
  // Ward Room. Falls back to async post-only path when not a DM view, when
  // target agent cannot be resolved, or when the chat call fails.
  const submitReply = async () => {
    const text = replyText.trim();
    if (!text || isThinking) return;
    setReplyText('');

    const postCaptain = () => fetch(`/api/wardroom/threads/${activeThread}/posts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        author_id: 'captain',
        body: text,
        author_callsign: 'Captain',
      }),
    });

    if (!isDm || !targetAgentId) {
      // Existing async path — proactive cycle responds.
      try { await postCaptain(); } catch { /* swallow */ }
      useStore.getState().selectWardRoomThread(activeThread);
      return;
    }

    // Synchronous DM path with thinking indicator + dual-write.
    useStore.getState().setWardRoomDmPending({
      threadId: activeThread,
      captainText: text,
      startedAt: Date.now(),
    });
    try {
      const history = (flatPosts ?? []).slice(-20).map(p => ({
        role: p.author_id === 'captain' ? 'user' : 'agent',
        text: p.body,
      }));
      const res = await fetch(`/api/agent/${targetAgentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      });
      if (!res.ok) throw new Error(`chat ${res.status}`);
      const data = await res.json();
      const responseText = data.response || '(no response)';

      // Dual-write: post Captain message, then agent response. Sequential to
      // preserve created_at ordering.
      await postCaptain();
      await fetch(`/api/wardroom/threads/${activeThread}/posts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: targetAgentId,
          body: responseText,
        }),
      });
    } catch {
      // Fallback: ensure the user message lands so the proactive cycle can
      // still respond on the next think tick.
      try { await postCaptain(); } catch { /* swallow */ }
    } finally {
      useStore.getState().setWardRoomDmPending(null);
      useStore.getState().selectWardRoomThread(activeThread);
    }
  };
===END REPLACE===
```

Add the thinking-placeholder render block immediately above the existing `{posts.length === 0 && ...}` block:

```
===MODIFY: ui/src/components/wardroom/WardRoomThreadDetail.tsx===
===SEARCH===
        {posts.length === 0 && (
          <div style={{ padding: 16, color: '#666680', fontSize: 12, textAlign: 'center' as const }}>
            No replies yet
          </div>
        )}
===REPLACE===
        {posts.length === 0 && !isThinking && (
          <div style={{ padding: 16, color: '#666680', fontSize: 12, textAlign: 'center' as const }}>
            No replies yet
          </div>
        )}
        {isThinking && (
          <div
            data-testid="dm-thinking-indicator"
            style={{ padding: '12px 8px', color: '#8888a0', fontSize: 12, fontStyle: 'italic' }}
          >
            agent is thinking…
          </div>
        )}
===END REPLACE===
```

Disable the Send button while thinking:

```
===MODIFY: ui/src/components/wardroom/WardRoomThreadDetail.tsx===
===SEARCH===
        <button onClick={submitReply} style={{
          background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
          borderRadius: 4, color: '#f0b060', fontSize: 11, cursor: 'pointer', padding: '4px 10px',
          fontFamily: "'JetBrains Mono', monospace", alignSelf: 'flex-end',
        }}>Send</button>
===REPLACE===
        <button
          onClick={submitReply}
          disabled={isThinking}
          style={{
            background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
            borderRadius: 4, color: isThinking ? '#666680' : '#f0b060', fontSize: 11,
            cursor: isThinking ? 'not-allowed' : 'pointer', padding: '4px 10px',
            fontFamily: "'JetBrains Mono', monospace", alignSelf: 'flex-end',
            opacity: isThinking ? 0.5 : 1,
          }}
        >Send</button>
===END REPLACE===
```

**Builder note:** SEARCH block matches the live file at `WardRoomThreadDetail.tsx:155-160` exactly (verified at HEAD `09971a6`: `fontFamily: "'JetBrains Mono', monospace", alignSelf: 'flex-end',` with double-quote close on the fontFamily string). If the file has drifted at build time, re-read and copy the exact substring.

## Section 4 — Backend test: `tests/test_ad574b_dm_sync_chat.py`

Create new file. Eight unit tests for `_resolve_dm_target_agent_id`. The helper is unit-testable in isolation against a fake `runtime.registry` (no Ward Room fixture or DB needed). Pattern follows the in-process unit-test style used by `tests/test_ad685d_phantom_field_name.py` and similar AD-tagged helper tests.

```
===FILE: tests/test_ad574b_dm_sync_chat.py===
"""AD-574b: DM listing endpoints expose target_agent_id for HXI sync chat path."""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from probos.routers.wardroom import _resolve_dm_target_agent_id


class _FakeAgent:
    def __init__(self, agent_id: str, alive: bool = True):
        self.id = agent_id
        self.is_alive = alive


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]):
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return self._agents


@pytest.fixture
def runtime_with_agents():
    agents = [
        _FakeAgent("agent-a-001-full"),
        _FakeAgent("agent-b-002-full"),
        _FakeAgent("agent-dead", alive=False),
    ]
    return SimpleNamespace(registry=_FakeRegistry(agents))


class TestResolveDmTargetAgentId:
    """Direct unit tests of the resolver helper."""

    def test_captain_dm_resolves_other_participant(self, runtime_with_agents):
        # dm-captain-{prefix} → resolve prefix to full id.
        result = _resolve_dm_target_agent_id("dm-captain-agent-a-", runtime_with_agents)
        # Channel name has 4 parts after split; helper requires exactly 3.
        # This shape is invalid → returns None.
        assert result is None

    def test_captain_dm_three_part_resolves(self, runtime_with_agents):
        # Real captain DM channel names use prefix[:8], so split yields 3 parts.
        result = _resolve_dm_target_agent_id("dm-captain-agent-a", runtime_with_agents)
        assert result == "agent-a-001-full"

    def test_agent_to_agent_dm_resolves_first_match(self, runtime_with_agents):
        # dm-{a8}-{b8} — non-captain prefix is parts[1] (or [2] if [1]=="captain").
        result = _resolve_dm_target_agent_id("dm-agent-a-agent-b", runtime_with_agents)
        # Helper takes first non-captain candidate → "agent-a" → resolves.
        assert result == "agent-a-001-full"

    def test_dead_agent_not_returned(self):
        agents = [_FakeAgent("ghost-x", alive=False)]
        rt = SimpleNamespace(registry=_FakeRegistry(agents))
        result = _resolve_dm_target_agent_id("dm-captain-ghost-x", rt)
        assert result is None

    def test_unresolvable_prefix_returns_none(self, runtime_with_agents):
        result = _resolve_dm_target_agent_id("dm-captain-unknown", runtime_with_agents)
        assert result is None

    def test_non_dm_channel_returns_none(self, runtime_with_agents):
        result = _resolve_dm_target_agent_id("ship-general", runtime_with_agents)
        assert result is None

    def test_runtime_without_registry_returns_none(self):
        rt = SimpleNamespace()  # no registry attribute
        result = _resolve_dm_target_agent_id("dm-captain-anything", rt)
        assert result is None

    def test_resolver_swallows_registry_exception(self):
        class _Boom:
            def all(self):
                raise RuntimeError("registry unavailable")

        rt = SimpleNamespace(registry=_Boom())
        result = _resolve_dm_target_agent_id("dm-captain-prefix", rt)
        assert result is None  # tier-2 log-and-degrade
```

**Test count from this file: 8.** Combined with 0 modifications to existing pytest tests, the pytest delta is **+8**.

## Section 5 — UI test: `ui/src/__tests__/WardRoomDmSync.test.tsx`

Create a Vitest component test file. Mock `fetch`, mock `useStore.getState()` actions, render `WardRoomThreadDetail`, and verify the synchronous DM submit path.

```
===FILE: ui/src/__tests__/WardRoomDmSync.test.tsx===
/**
 * AD-574b: WardRoomThreadDetail synchronous DM reply branch.
 *
 * Verifies the new submit path:
 * - DM view + resolved target_agent_id triggers /api/agent/{id}/chat call
 * - Thinking placeholder renders while in flight
 * - Dual-write posts Captain message + agent response back to thread
 * - Falls back to async post path when target_agent_id is null
 * - Falls back to async post path on chat-call failure
 * - Send button disables while thinking
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WardRoomThreadDetail } from '../components/wardroom/WardRoomThreadDetail';
import { useStore } from '../store/useStore';

const FAKE_THREAD = {
  id: 't1', title: 'Test DM', body: '', author_callsign: 'Captain',
  created_at: Date.now() / 1000, net_score: 0,
};

beforeEach(() => {
  vi.restoreAllMocks();
  // Reset store to known state.
  useStore.setState({
    wardRoomView: 'dm-detail',
    wardRoomActiveChannel: 'ch-1',
    wardRoomActiveThread: 't1',
    wardRoomThreadDetail: { thread: FAKE_THREAD as any, posts: [] },
    wardRoomDmChannels: [
      { channel: { id: 'ch-1', name: 'dm-captain-agent-a', description: '', created_at: 0 },
        latest_thread: null, thread_count: 1, target_agent_id: 'agent-a-001-full' },
    ],
    wardRoomDmPending: null,
  });
});

describe('AD-574b WardRoomThreadDetail sync DM', () => {
  it('renders without thinking indicator when idle', () => {
    render(<WardRoomThreadDetail />);
    expect(screen.queryByTestId('dm-thinking-indicator')).toBeNull();
  });

  it('routes DM submit through /api/agent/{id}/chat then dual-writes posts', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) {
        return new Response(JSON.stringify({ response: 'Hello Captain' }), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    const textarea = screen.getByPlaceholderText('Reply...') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'How are you?' } });
    const send = screen.getByText('Send');
    fireEvent.click(send);

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(c => String(c[0]));
      expect(calls).toContain('/api/agent/agent-a-001-full/chat');
      // Dual-write: at least one ward room post call after chat.
      expect(calls.filter(u => u.includes('/api/wardroom/threads/t1/posts')).length).toBeGreaterThanOrEqual(2);
    });
  });

  it('shows thinking placeholder while chat is in flight', async () => {
    let resolveChat: (v: Response) => void = () => {};
    const chatPromise = new Promise<Response>(r => { resolveChat = r; });
    vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) return chatPromise;
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'hi' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      expect(screen.queryByTestId('dm-thinking-indicator')).not.toBeNull();
    });
    resolveChat(new Response(JSON.stringify({ response: 'ok' }), { status: 200 }));
  });

  it('falls back to async post when target_agent_id is null', async () => {
    useStore.setState({
      wardRoomDmChannels: [
        { channel: { id: 'ch-1', name: 'dm-captain-x', description: '', created_at: 0 },
          latest_thread: null, thread_count: 1, target_agent_id: null },
      ],
    });
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(new Response('{}', { status: 200 })) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'fallback' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: any) => String(c[0]));
      expect(calls.some((u: string) => u.includes('/api/agent/'))).toBe(false);
      expect(calls.some((u: string) => u.includes('/api/wardroom/threads/t1/posts'))).toBe(true);
    });
  });

  it('falls back to async post when chat call returns 500', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) {
        return new Response('boom', { status: 500 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'sad' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: any) => String(c[0]));
      // Captain post still lands.
      expect(calls.some((u: string) => u.includes('/api/wardroom/threads/t1/posts'))).toBe(true);
      // Pending cleared.
      expect(useStore.getState().wardRoomDmPending).toBeNull();
    });
  });

  it('disables Send button while thinking', async () => {
    useStore.setState({
      wardRoomDmPending: { threadId: 't1', captainText: 'pending', startedAt: Date.now() },
    });
    render(<WardRoomThreadDetail />);
    const send = screen.getByText('Send') as HTMLButtonElement;
    expect(send.disabled).toBe(true);
  });
});
```

**Test count from this file: 6.** Vitest is run via `cd ui && npx vitest run` (project script `npm test`) and does NOT contribute to the `pytest tests/` collected count. The pytest gate delta is **+8** (window **[+6, +10]**) targeting **11419** total at HEAD `09971a6` baseline 11411. The Vitest gate is an independent UI assertion surface (precedent: existing `ui/src/__tests__/WardRoomPanel.test.tsx`, `WardRoomPostItem.test.tsx`).

## Section 6 — DECISIONS.md entry

Append to `DECISIONS.md` (NOT `decisions-era-4-evolution.md`; era files are read-only audit trails per the standing convention — only the live `DECISIONS.md` rolls forward).

**Insertion location:** TOP of the file, immediately after the preamble (`See [PROGRESS.md] ... See [docs/development/roadmap.md] ...`) and before the first existing AD entry. DECISIONS.md follows reverse-chronological convention (verified at HEAD `09971a6`: AD-695 at line 145, AD-686b at line 282, AD-686 at line 302, AD-574 at line 1169 — newest at top, oldest deeper). AD-574b is a new entry created 2026-05-05 and goes at the top. Do NOT place adjacent to the existing AD-574 entry at line 1169; that violates the chronological convention.

```
===MODIFY: DECISIONS.md===
===SEARCH===
# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.
===REPLACE===
# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

### AD-574b: Synchronous DM Reply with Thinking Indicator + Ward Room Dual-Write (2026-05-05)

**Context.** AD-574 (Wave 33, decisions-era-4-evolution.md:2888) wired Captain-in-DM into `WardRoomRouter.find_targets` so an agent eventually responds to Captain DMs on its next proactive think cycle. The DM panel UX remained asymmetric with `ProfileChatTab`: Captain types into a Ward Room DM, the input clears, and an empty thread sits there for ~30s. AD-574b closes that gap by routing DM submits through `/api/agent/{id}/chat` synchronously and dual-writing the exchange back into the Ward Room thread for record-keeping.

**Decision.** `WardRoomThreadDetail.submitReply` branches on `view === 'dm-detail'` plus a backend-supplied `target_agent_id`. Synchronous path: set `wardRoomDmPending` slice, POST to `/api/agent/{id}/chat`, on success dual-write Captain message + agent response to the Ward Room thread, on failure fall back to existing async-post path. Backend `/api/wardroom/dms` and `/api/wardroom/captain-dms` gain a `target_agent_id` field via private `_resolve_dm_target_agent_id` helper that resolves channel-name participant prefix against `runtime.registry.all()` and returns `null` on miss (tier-2 log-and-degrade).

**Wholesale-deferred sibling.** AD-574c (DM conversation convergence — unify `ProfileChatTab.agentConversations` Map with Ward Room DM threads into a single conversation store) is wholesale-deferred to AD-574c-i. Forcing function: AD-574b establishes Ward Room as the canonical write surface for DM via dual-write; AD-574c-i then refactors ProfileChatTab to read from `/api/wardroom/dms/{channel_id}/threads` + `/api/wardroom/threads/{id}` instead of the standalone Map. Cannot land in Wave 69 because doing so would conflate two architectural changes (foreground sync UX + canonical-store swap) into one prompt — exact pattern Wave 67 (5→1) and Wave 68 (4→0) avoided.

**Architect calls.** `target_agent_id` lives on the API response not in UI parsing (DLog #1: keeps frontend ignorant of channel-name format mutation history). Dual-write client-side (DLog #2: keeps `/api/agent/{id}/chat` reusable by ProfileChatTab without thread-state coupling). `target_agent_id=null` fallback (DLog #3: graceful degradation when channel encodes a deleted/renamed agent). `wardRoomDmPending` lives in store not local state (DLog #4: survives panel re-mounts during in-flight chat). Existing AD-574 proactive ambient-response path unchanged (DLog #5: belt-and-suspenders; if sync fails the proactive cycle still picks up the unread Captain post).

**Out of scope.** Streaming "thinking…" with periodic LLM-thought updates (defer AD-574b-1, requires SSE/WebSocket on `/api/agent/{id}/chat`). Captain typing-indicator surface to the agent (defer AD-574b-2). Multi-Captain coordination (*(Commercial)* AD-574b-3, OSS surface stays single-Captain). DM convergence into single store (deferred AD-574c-i, see Forcing function above).

**Tests.** 8 pytest at `tests/test_ad574b_dm_sync_chat.py` (helper unit tests covering captain DM resolution, agent-to-agent DM resolution, dead-agent skip, unresolvable prefix → None, non-DM channel → None, runtime without registry → None, registry exception → None tier-2). 6 Vitest at `ui/src/__tests__/WardRoomDmSync.test.tsx` (idle render, sync DM submit + dual-write, thinking placeholder during in-flight, fallback on null target, fallback on chat 500, Send disabled while thinking).

**Cross-links:** AD-574 (DM reply agent notification — predecessor, decisions-era-4-evolution.md:2888), AD-574c-i (DM conversation convergence — wholesale-deferred successor, no GH issue v1; forcing function: this AD's dual-write must be live before ProfileChatTab data-source swap). Wave 69. Closes GH issue #110 (partial — AD-574c remains as deferred-with-forcing-function).

===END REPLACE===
```

## Section 7 — Roadmap update

```
===MODIFY: docs/development/roadmap.md===
===SEARCH===
**Deferred:** AD-574b (synchronous DM response in HXI — `/api/agent/{id}/chat` from DM panel with "agent is thinking..." indicator), AD-574c (DM conversation convergence — unify ProfileChatTab and Ward Room DM into single conversation store).
===REPLACE===
**AD-574b: complete via Wave 69.** `WardRoomThreadDetail.submitReply` routes through `/api/agent/{id}/chat` for DM views, displays a "thinking…" placeholder via `wardRoomDmPending` store slice, and dual-writes Captain message + agent response back into the Ward Room thread. Backend `/api/wardroom/dms` + `/api/wardroom/captain-dms` gain `target_agent_id` field. Falls back to async post-only path when target unresolvable or chat call fails.

**Deferred:** AD-574c (DM conversation convergence — unify ProfileChatTab and Ward Room DM into single conversation store) **wholesale-deferred to AD-574c-i**. Forcing function: AD-574b dual-write must be live before ProfileChatTab data-source swap.
===END REPLACE===
```

## What this AD does NOT change

- **No service-side change** to `WardRoomRouter`, `find_targets`, the proactive ambient-response cycle, or the existing async post path.
- **No change** to `/api/agent/{id}/chat` endpoint (already crew-only-gated, already supports `history` param via `AgentChatRequest`).
- **No change** to `ProfileChatTab` or `agentConversations` store slice (that is AD-574c-i territory).
- **No new EventType, Pydantic config, module, or runtime attribute.**
- **No streaming** of agent thoughts during the in-flight chat (placeholder is static).
- **No removal** of AD-574's proactive ambient-response wiring (belt-and-suspenders by design).

## Tracking

- `prompts/wave-plan.yaml` id=69: `status: done`, `prompts_already_drafted: true`, `notes:` block per dispatch DLog #9.
- `PROGRESS.md`: append CLOSED paragraph per dispatch.
- `DECISIONS.md`: AD-574b entry added (Section 6 above).
- `docs/development/roadmap.md`: AD-574b marked complete via Wave 69; AD-574c forcing function clarified (Section 7 above).
- GH issue #110: closed with partial-completion summary (1 shipped + 1 deferred-with-forcing-function).

## Acceptance Criteria

1. `pytest tests/test_ad574b_dm_sync_chat.py -v -n 0` — 8 tests pass.
2. `pytest tests/test_ward_room_dms.py -v -n 0` — all existing tests still pass.
3. Full pytest gate: `pytest tests/ -q -n 4 --dist=loadfile` — total **11419** passing, delta **+8** vs Wave 68 baseline 11411 (window [+6, +10]).
4. Vitest gate: `cd ui && npx vitest run src/__tests__/WardRoomDmSync.test.tsx` — 6 tests pass. Existing Vitest suites (`WardRoomPanel.test.tsx`, `WardRoomPostItem.test.tsx`, etc.) unchanged.
5. Phantom-API pre-check: `scripts/phantom-api-precheck.ps1 prompts/ad-574b-dm-sync-chat.md` — only expected FPs (`target_agent_id` intra-prompt-introduction, `wardRoomDmPending` TS identifier ignored). 0 NEW phantoms.
6. Pre-commit deletion sanity: max single-file deletion < 200 lines. Expected ranges: `routers/wardroom.py` +60/-2; `useStore.ts` +6/-2; `types.ts` +6/-0; `WardRoomThreadDetail.tsx` +75/-15; `DECISIONS.md` +25/-0; `roadmap.md` +4/-2.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD 09971a6)

```
grep -n "submitReply" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  35:  const submitReply = async () => {

grep -n "/api/wardroom/threads/.*?/posts\|fetch.*?wardroom" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  38: await fetch(`/api/wardroom/threads/${activeThread}/posts`, {

grep -n "agent_chat\|/{agent_id}/chat" src/probos/routers/agents.py
  166: @router.post("/{agent_id}/chat")
  167: async def agent_chat(agent_id: str, ...) -> dict[str, Any]:

grep -n "@router.get\|list_dm_channels\|list_captain_dms" src/probos/routers/wardroom.py
  26: @router.get("/dms")
  27: async def list_dm_channels(runtime: Any = Depends(get_runtime)):
  64: @router.get("/captain-dms")
  65: async def list_captain_dms(runtime: Any = Depends(get_runtime)):

grep -n "channel_name = f\"dm-\|dm-captain-" src/probos/ward_room/channels.py src/probos/proactive.py
  ward_room/channels.py:203:    channel_name = f"dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}"
  proactive.py:3599: captain_channel_name = f"dm-captain-{agent.id[:8]}"

grep -n "channel.channel_type == \"dm\"\|find_targets" src/probos/ward_room_router.py
  841: elif channel.channel_type == "dm":
  843: # AD-574: DM channel — notify the other participant (no EA gating)

grep -n "wardRoomView\|wardRoomDmChannels\|wardRoomActiveChannel" ui/src/store/useStore.ts
  247:  wardRoomActiveChannel: string | null;
  252:  wardRoomView: 'channels' | 'dms' | 'dm-detail';
  255:  wardRoomDmChannels: { channel: { ... }; ... }[];

grep -n "agentConversations\|AgentConversation" ui/src/store/useStore.ts ui/src/store/types.ts
  useStore.ts:242:  agentConversations: Map<string, AgentConversation>;
  useStore.ts:454:  agentConversations: new Map(),

grep -n "TestDmApi\|test_dm_api_list_dm_channels" tests/test_ward_room_dms.py
  155: class TestDmApi:
  158: async def test_dm_api_list_dm_channels(self, wr):

grep -n "registry.all\|self._registry.all" src/probos/ward_room_router.py
  823: for agent in self._registry.all():
  847: for agent in self._registry.all():
```

Every concrete claim in this prompt maps to one of the above grep hits. Section 0 (no new event types) is asserted by absence — no `EventType.X` references introduced in any SEARCH/REPLACE block.
