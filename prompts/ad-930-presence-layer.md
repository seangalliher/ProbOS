# AD-930: Crew Presence Layer (Teams-style online / working / in-meeting dots)

**Status:** Drafted, not built.
**Target repo:** OSS (`d:\ProbOS`).
**Highest committed AD-numbered work:** AD-929 (`72f4eb6b`). **Current HEAD:** `2eb8cabd` (the AD-925 config flip, pushed, `origin/main`). **AD-930 is unused** — it appears only as a forward-marker in the non-goals of DECISIONS.md / `prompts/ad-928-*` / `prompts/ad-929-*`. No `/api/crew/presence` endpoint exists.
**Estimated tests:** +9 pytest, +12 Vitest.

---

## Problem

The Captain asked for "a good indicator to see if the agent is actively working or in a meeting" — the Microsoft-Teams-signature presence dot (green/amber/blue/grey) on each crew member. This is the **last Teams-signature gap** in the collaboration experience (group chat AD-913→919, meetings AD-920→923, task-workspace rooms AD-925→929 all shipped).

Every signal a presence layer needs **already exists** — AD-930 **aggregates**, it does not invent telemetry:

| Presence facet | Verified live signal |
|---|---|
| **alive / online** | `BaseAgent.is_alive` (`AgentState` ∈ {ACTIVE, DEGRADED}) over `runtime.registry.all()` filtered by `is_crew_agent` |
| **in a meeting** | AD-920 `metadata.meeting_active` on a chat thread + the agent in `thread.participants` |
| **working** | `AgentMeta.last_active` (bumped post-operation) within a recency window — an **honest recent-activity proxy** |

**The "working" honesty (read this).** There is **no canonical per-agent "currently in-flight / executing-right-now" flag at HEAD** — `src/probos/avatars/telemetry.py:24` states it verbatim: `load` is a v1 approximation (`1.0 if mouth_active else 0.0`, i.e. TTS speaking, not task work) because there is *"no canonical per-agent backend source at HEAD."* The honest, real signal that *does* exist is `AgentMeta.last_active` (`src/probos/types.py:40`), bumped in `BaseAgent.update_confidence()` (`src/probos/substrate/agent.py:109`) after each completed operation — tool dispatch (`agents/file_reader.py:62`, `file_search.py:52`, `directory_list.py:52`, `red_team.py`), `CognitiveAgent.handle_intent()` (the crew DM / chat-fan-out / work-item-dispatch reply path — documented in the AD-553/BF-023 history), and the proactive loop's confidence update (BF-023). It is already consumed as a recency signal at `cognitive/introspective_telemetry.py:111` (`last_action_minutes`). So v1 **`working` = "completed an operation within `presence_working_window_seconds`"** — a recent-activity proxy, NOT a fabricated in-flight flag. A true in-flight signal is the forward marker **AD-930a**.

---

## Solution overview

1. **Presence model** — a 4-state string enum with a clear precedence.
2. **One read-only endpoint** `GET /api/crew/presence` on the existing `/api/crew` router — computes per-crew-agent presence from the three verified signals.
3. **UI** — a pure `PresenceDot` (small colored SVG circle, amber pulse for working), a `presence` store slice polled while the roster is open, the dot mounted on each `CrewRosterPanel` row, and an optional opt-in `presence?` prop on the reusable `AgentAvatarBadge`.

### Presence model (the enum + precedence)

```
PresenceState = offline | online | working | in_meeting
```

Computed per crew agent (keyed by `agent_id` — the registry instance id, which is also what thread `participants` and `meta` are keyed on):

```
if not agent.is_alive:              -> "offline"   # SPAWNING / RECYCLING / absent
elif agent_id in meeting_ids:       -> "in_meeting"
elif now - meta.last_active < W:    -> "working"   # recent-activity proxy
else:                               -> "online"    # alive + idle
```

**Liveness is the floor** (a not-alive agent is `offline` even if still listed as a thread participant). **Among alive agents the precedence is `in_meeting > working > online`** (the Captain's stated order — an agent both recently-active *and* in a meeting reads as `in_meeting`, matching Teams' "In a meeting" busy variant).

---

## Verified context (file:line, grepped against HEAD `2eb8cabd`)

**Backend**
- `src/probos/routers/crew.py:32` `router = APIRouter(prefix="/api/crew", tags=["crew"])` — **already registered**; `:35` `@router.get("/roster")` is the sibling pattern to mirror (async, `Depends(get_runtime)`, `is_crew_agent`, Tier-2 `logger.debug` degrade). Imports at `:20-28`: `logging`, `typing.Any`, `fastapi`, `is_crew_agent`, `get_runtime`. **No `datetime` import yet — add one.**
- `src/probos/crew_utils.py` `is_crew_agent(agent, ontology)` — crew filter (ontology may be `None`).
- `src/probos/substrate/agent.py:100-101` `is_alive` → `self.state in (AgentState.ACTIVE, AgentState.DEGRADED)`; `:44` `self.meta = AgentMeta()`; `:109` `self.meta.last_active = datetime.now(timezone.utc)` inside `update_confidence()`.
- `src/probos/types.py:16` `class AgentState(Enum)` = SPAWNING / ACTIVE / DEGRADED / RECYCLING; `:36-40` `AgentMeta.last_active: datetime` (tz-aware, default `datetime.now(timezone.utc)`).
- `src/probos/avatars/telemetry.py:24` — the verbatim "no canonical per-agent backend source at HEAD" note for `load`/working.
- `src/probos/threads/__init__.py:88` `class ChatThread` — `participants: list[str]`, `metadata: dict` (carries AD-920 `meeting_active`); `list_threads(self, *, include_archived=False, project_id=None, task_id=None, limit=100)` (sync, ordered `last_active_at DESC`).
- `src/probos/runtime.py:450` `self.chat_thread_store = ChatThreadStore(...)` — the public attr to read.
- `config.py:4600` `class CommunicationsConfig(BaseModel)` (`dm_min_rank` `:4602`, plus AD-928 `status_min_rank`/`status_max_per_turn`/`status_max_bytes`) — where the new window field belongs.
- `src/probos/cognitive/introspective_telemetry.py:111` — precedent that already reads `agent.meta.last_active` for recency.

**UI**
- `ui/src/components/CrewRosterPanel.tsx` — binds `useStore(s => s.crewManifest)` (`CrewManifestEntry[]`); `CrewRow` renders a department dot + callsign + post + rank badge + trust bar. **This is the primary presence mount.** `DEPT_COLORS` palette present.
- `ui/src/components/AgentAvatarBadge.tsx` — pure `<span>` badge, props `{agentId, callsign, department?, size?}`, `data-testid="agent-avatar-badge"`. Used in IntentSurface multi-reply, `GroupChatListPanel`, `MeetingView` fallback. **Reusable secondary surface.**
- `ui/src/store/useStore.ts:377-378` `crewManifestOpen` / `crewManifest`; `:952-971` `openCrewManifest` — the **exact fetch+map idiom to mirror** (`fetch('/api/...')` → `res.ok` → `set({...})`, `catch { /* non-critical */ }`).
- `ui/src/store/types.ts:611` `CrewManifestEntry { agentType, callsign, department, post, rank, trustScore, agentId }`.
- `ui/src/__tests__/CrewRoster.bridge.test.tsx:29-30` — the BF-287 real-store seed pattern (`useStore.setState({ crewManifestOpen: true, crewManifest: [...] })`).
- Pulse idiom: co-located `<style>` `@keyframes`, canonical at `CrewCollaborationPanel.tsx:186-191` (`crew-subtask-pulse`).

---

## Implementation

### Section 1 — config field (`config.py`)

In `class CommunicationsConfig` (`config.py:4600`), **after** the AD-928 `status_max_bytes` field, add:

```python
    # AD-930: presence "working" = an operation completed within this many
    # seconds (recent-activity proxy via AgentMeta.last_active; there is no
    # true in-flight signal at HEAD — AD-930a). Read-only/computed, so this
    # ships ON by default (not a transitional behavioral flag).
    presence_working_window_seconds: float = 90.0
```

If `CommunicationsConfig` uses `field_validator`s (it does for the status caps), add one bounding `presence_working_window_seconds > 0` (mirror that pattern). Zero-config boot must stay byte-identical (sensible default present).

### Section 2 — endpoint (`src/probos/routers/crew.py`)

Add `from datetime import datetime, timezone` to the imports. Append a new route **after** `crew_roster`:

```python
@router.get("/presence")
async def crew_presence(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Teams-style per-crew presence — ``offline | online | working | in_meeting``.

    AD-930 aggregates existing signals; it invents no new telemetry:
      - liveness   -> ``agent.is_alive`` (registry ``AgentState`` ACTIVE/DEGRADED)
      - in_meeting -> the agent is a participant of a non-archived chat thread
                      whose ``metadata.meeting_active`` is set (AD-920)
      - working    -> ``agent.meta.last_active`` within
                      ``communications.presence_working_window_seconds`` — an
                      honest *recent-activity* proxy (last completed operation),
                      NOT a true in-flight flag (none exists at HEAD; AD-930a)

    Liveness is the floor: a not-alive agent is ``offline`` regardless of
    thread membership. Among alive agents: ``in_meeting > working > online``.
    Returns ``{"presence": {agent_id: state}, "count": N}`` for crew only.
    """
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return {"presence": {}, "count": 0}

    ontology = getattr(runtime, "ontology", None)
    crew_agents = [a for a in registry.all() if is_crew_agent(a, ontology)]

    # Recency window — comms-config tunable, sensible default, Tier-2 degrade.
    window = 90.0
    try:
        window = float(runtime.config.communications.presence_working_window_seconds)
    except Exception:
        logger.debug("crew_presence: window config unavailable; default 90s", exc_info=True)

    # Meeting participants — Tier-2 degrade: a store failure means no
    # in_meeting is computed and agents simply fall through to working/online.
    meeting_ids: set[str] = set()
    store = getattr(runtime, "chat_thread_store", None)
    if store is not None:
        try:
            for thread in store.list_threads(include_archived=False):
                if (getattr(thread, "metadata", None) or {}).get("meeting_active"):
                    meeting_ids.update(getattr(thread, "participants", None) or [])
        except Exception:
            logger.debug("crew_presence: meeting scan failed; in_meeting skipped", exc_info=True)

    now = datetime.now(timezone.utc)
    presence: dict[str, str] = {}
    for agent in crew_agents:
        agent_id = getattr(agent, "id", "") or ""
        if not agent_id:
            continue
        if not getattr(agent, "is_alive", False):
            presence[agent_id] = "offline"
            continue
        if agent_id in meeting_ids:
            presence[agent_id] = "in_meeting"
            continue
        state = "online"
        meta = getattr(agent, "meta", None)
        last_active = getattr(meta, "last_active", None)
        if last_active is not None:
            try:
                if (now - last_active).total_seconds() < window:
                    state = "working"
            except Exception:
                logger.debug("crew_presence: last_active compare failed for %s", agent_id, exc_info=True)
        presence[agent_id] = state

    return {"presence": presence, "count": len(presence)}
```

### Section 3 — UI types (`ui/src/store/types.ts`)

Add (next to `CrewManifestEntry`):

```ts
// AD-930: crew presence layer
export type PresenceState = 'offline' | 'online' | 'working' | 'in_meeting';
export type CrewPresenceMap = Record<string, PresenceState>;
```

### Section 4 — store slice (`ui/src/store/useStore.ts`)

Mirror the `openCrewManifest` idiom (NO open/close — presence is ambient data, not a panel). Add the import (`CrewPresenceMap`), the state field + initial, and the action:

- declaration: `presence: CrewPresenceMap;` and `fetchPresence: () => Promise<void>;`
- initial state: `presence: {},`
- action:

```ts
  fetchPresence: async () => {
    try {
      const res = await fetch('/api/crew/presence');
      if (res.ok) {
        const data = await res.json();
        set({ presence: (data.presence ?? {}) as CrewPresenceMap });
      }
    } catch { /* non-critical */ }
  },
```

### Section 5 — `PresenceDot` (NEW `ui/src/components/presence/PresenceDot.tsx`)

```tsx
// AD-930: Teams-style crew presence dot. Pure presentational.
// Color encodes presence; motion (amber pulse) encodes "working"
// (HXI #4 — motion communicates state). Inline SVG circle, NO emoji (HXI #3).
import type { PresenceState } from '../../store/types';

const PRESENCE_COLOR: Record<PresenceState, string> = {
  online: '#60c070',     // alive + idle — calm green
  working: '#f0b060',    // active — amber (HXI active color), pulses
  in_meeting: '#5090d0', // in a meeting room — blue
  offline: '#666680',    // not alive — dim
};

const PRESENCE_LABEL: Record<PresenceState, string> = {
  online: 'Online',
  working: 'Working',
  in_meeting: 'In a meeting',
  offline: 'Offline',
};

export function PresenceDot({ state, size = 8, title }: {
  state: PresenceState;
  size?: number;
  title?: string;
}) {
  const color = PRESENCE_COLOR[state] ?? PRESENCE_COLOR.offline;
  const label = title ?? PRESENCE_LABEL[state] ?? 'Offline';
  const pulsing = state === 'working';
  return (
    <>
      <style>{`@keyframes presenceDotPulse{0%,100%{opacity:1}50%{opacity:.45}}`}</style>
      <span
        data-testid="presence-dot"
        data-presence={state}
        data-pulse={pulsing ? 'true' : undefined}
        role="img"
        aria-label={label}
        title={label}
        style={{
          display: 'inline-block',
          width: size,
          height: size,
          borderRadius: '50%',
          background: color,
          flexShrink: 0,
          boxShadow: pulsing ? `0 0 4px ${color}` : 'none',
          animation: pulsing ? 'presenceDotPulse 1.8s ease-in-out infinite' : 'none',
        }}
      />
    </>
  );
}
```

### Section 6 — mount on the roster (`ui/src/components/CrewRosterPanel.tsx`)

- Import: `import { PresenceDot } from './presence/PresenceDot';` and `import type { PresenceState } from '../store/types';`
- In `CrewRosterPanel`, read the slice + poll while open:

```tsx
  const presence = useStore(s => s.presence);
  const fetchPresence = useStore(s => s.fetchPresence);

  useEffect(() => {
    if (!open) return;
    fetchPresence();
    const id = window.setInterval(fetchPresence, 10000);
    return () => window.clearInterval(id);
  }, [open, fetchPresence]);
```

- Pass the per-row state into `CrewRow`:

```tsx
              <CrewRow
                key={entry.agentType}
                entry={entry}
                presenceState={presence[entry.agentId] ?? 'offline'}
                onClickProfile={() => { if (entry.agentId) openProfile(entry.agentId); }}
              />
```

- Extend `CrewRow`'s props (`presenceState: PresenceState`) and render the dot beside the callsign:

```tsx
        <div style={{ fontSize: 11, fontWeight: 600, color: '#e0dcd4', display: 'flex', alignItems: 'center', gap: 6 }}>
          <PresenceDot state={presenceState} size={7} />
          {entry.callsign}
        </div>
```

### Section 7 — optional reusable overlay (`ui/src/components/AgentAvatarBadge.tsx`)

Add an **optional** `presence?: PresenceState` prop. **When omitted (every existing call site) return the original single `<span>` byte-identical** — backward compatible, no existing badge test changes. When provided, wrap and overlay a corner dot:

```tsx
import { PresenceDot } from './presence/PresenceDot';
import type { CSSProperties } from 'react';
import type { PresenceState } from '../store/types';

interface Props {
  agentId: string;
  callsign: string;
  department?: string;
  size?: 24 | 32;
  presence?: PresenceState; // AD-930: optional Teams-style status overlay
}

export function AgentAvatarBadge({ agentId: _agentId, callsign, department = '', size = 24, presence }: Props) {
  // ...existing color/initial/style unchanged...
  const badge = (
    <span style={style} aria-label={`Agent ${callsign}`} data-testid="agent-avatar-badge">
      {initial}
    </span>
  );
  if (!presence) return badge;
  return (
    <span style={{ position: 'relative', display: 'inline-flex', flexShrink: 0 }}>
      {badge}
      <span style={{ position: 'absolute', right: -1, bottom: -1, borderRadius: '50%', padding: 1, background: '#0a0a12' }}>
        <PresenceDot state={presence} size={Math.max(6, Math.round(size * 0.34))} />
      </span>
    </span>
  );
}
```

Wiring real presence data into badge consumers across the app needs a global poll → forward marker **AD-930b**. In v1 only the roster feeds presence; the badge prop is the reusable primitive.

---

## Tests

### Backend — `tests/test_ad930_presence.py` (+9, BF-287)

Real `ChatThreadStore` on `tmp_path` + a real `_FakeRegistry` of `_FakeAgent` duck-stubs exposing `id`, `agent_type`, `is_alive`, `meta.last_active`, plus a real `CommunicationsConfig` (or `SystemConfig()`). Direct-`await` `crew_presence` with a `SimpleNamespace`/stub runtime (`registry`, `ontology=None`, `chat_thread_store=<real store>`, `config.communications=<real>`). **No MagicMock at the store boundary.** Drive `is_crew_agent` via the ontology-`None` legacy crew set (or stub agent types it recognizes).

1. **in_meeting** — agent is a participant of a thread written with `metadata={"meeting_active": True}` → `"in_meeting"`.
2. **working** — alive crew agent, `meta.last_active = now` → `"working"`.
3. **online** — alive crew agent, `meta.last_active = now - 10min` (beyond the 90s window) → `"online"`.
4. **offline** — registered crew agent with `state` not alive (`SPAWNING`/`RECYCLING`, `is_alive False`) → `"offline"`.
5. **non-crew excluded** — a non-crew agent is absent from the `presence` map.
6. **precedence** — agent both recently-active AND a meeting participant → `"in_meeting"` (in_meeting beats working).
7. **registry None** → `{"presence": {}, "count": 0}`.
8. **store None degrade** — `chat_thread_store=None` → no crash; alive agents resolve to `working`/`online` (no `in_meeting`).
9. **count integrity** — `count == len(presence)` and equals the crew-agent count.

### UI — Vitest (+12 across 3 files)

- `ui/src/components/presence/__tests__/PresenceDot.test.tsx` (**6**): renders `data-presence` for each of `online`/`working`/`in_meeting`/`offline` with the matching color; `working` carries `data-pulse="true"`; no-emoji guard on `container.innerHTML` (and the `?raw` source per the established idiom).
- `ui/src/components/__tests__/CrewRosterPanel.presence.test.tsx` (**3**): with `useStore.setState({ crewManifestOpen: true, crewManifest: [...], presence: { '<id>': 'working' } })` a row renders a `presence-dot` with `data-presence="working"`; an agent absent from `presence` renders `offline`; no-emoji guard. (Mirror `CrewRoster.bridge.test.tsx` real-store seeding; if the poll `setInterval` needs taming, mock `fetchPresence`.)
- `ui/src/components/__tests__/AgentAvatarBadge.presence.test.tsx` (**3**): `presence="in_meeting"` → overlay `presence-dot` present with `data-presence="in_meeting"`; **no `presence` prop → no `presence-dot`** (backward-compat); no-emoji guard.

**Baseline:** AD-929 UI = **1225 passed / 1 skipped (207 files)**. Require ≥ **1237** passing.

---

## What this does NOT change (Do NOT build)

- **NO true in-flight "currently executing" signal and NO new telemetry infrastructure.** `working` is the `meta.last_active` recent-activity proxy. A real in-flight flag is **AD-930a** (forward marker).
- **NO activity feed / status messages** — that is AD-928 (`[STATUS]`). Presence is a dot, not a log.
- **NO global app-wide presence poll** wiring every badge surface — **AD-930b** (forward marker). v1 = roster-scoped poll + the optional `AgentAvatarBadge.presence` primitive.
- **NO new WebSocket channel and NO riding the fleet avatar-telemetry stream.** A polled `GET /api/crew/presence` is the v1 path (simplest, least-invasive, exactly-once computed server-side).
- **NO `degraded` / `away` presence states** — v1 ships the four the Captain named. DEGRADED agents are `is_alive`, so they read as `online`/`working` (a `degraded`/`away` state is a forward marker).
- **NO change** to `AgentState`/`LifecycleState` enums, `BaseAgent`, `AgentMeta`, `ChatThreadStore`, the `/api/crew/roster` or `/api/ontology/crew-manifest` endpoints, `MeetingView`, `GroupChatHeader`, `ParametricAvatar`/`CrewVRM`, consensus/trust, `IntentMessage`, or `Glyphs.tsx`.
- **NO new EventType, NO new REST router** (extend `crew.py`), **NO new config class** (extend `CommunicationsConfig`), **NO new store method beyond `fetchPresence`**.

---

## Tracking

- `docs/development/roadmap.md` — add an **AD-930** row (Task workspace / collaboration section) describing the presence layer + the AD-930a/930b forward markers.
- `PROGRESS.md` — prepend an AD-930 block on completion.
- `DECISIONS.md` — add an AD-930 entry (the 4-state model + precedence, the recent-activity-proxy honesty for `working`, the polled-endpoint-over-stream choice, the non-goals).
- Builder commits **LOCAL ONLY** unless the Captain has authorized pushing the held epic — confirm before `git push`.

## Acceptance criteria

- `GET /api/crew/presence` returns `{"presence": {agent_id: state}, "count": N}` for crew only, with the verified precedence (offline floor; `in_meeting > working > online` among alive agents), honest-degrading on `registry None` / `chat_thread_store None` / config-missing.
- `working` is computed from `AgentMeta.last_active` within `CommunicationsConfig.presence_working_window_seconds` (default 90.0) — documented as a recent-activity proxy, not an in-flight flag.
- `PresenceDot` renders the correct color per state with an amber pulse for `working`, no emoji; the roster shows a dot per row; `AgentAvatarBadge` is backward-compatible (no dot without the prop).
- Backend focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad930_presence.py tests/test_communications_settings.py -q -n 0` green; blast-radius `-k "crew or presence or roster or thread or chat or communications"` green (report the subset count).
- UI: `cd ui; npx vitest run` ≥ **1237** passing (+12); `npm run build` (tsc -b + vite) clean.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-08, HEAD `2eb8cabd`)

```
git log --oneline -1
  2eb8cabd config: enable auto-create task workspace rooms (AD-925 opt-in)   # HEAD = pushed; AD-929 (72f4eb6b) = highest AD commit
git grep -n "AD-930"            # only forward-marker mentions in DECISIONS.md / prompts/ad-928 / prompts/ad-929 — UNUSED
git grep -n "api/crew/presence" # (empty) — no presence endpoint exists

routers/crew.py:32   router = APIRouter(prefix="/api/crew", tags=["crew"])      # registered; add /presence here
routers/crew.py:35   @router.get("/roster")                                     # async + Depends(get_runtime) + is_crew_agent sibling
substrate/agent.py:101  return self.state in (AgentState.ACTIVE, AgentState.DEGRADED)   # is_alive
substrate/agent.py:109  self.meta.last_active = datetime.now(timezone.utc)      # bumped in update_confidence()
types.py:16          class AgentState(Enum)   # SPAWNING/ACTIVE/DEGRADED/RECYCLING
types.py:40          last_active: datetime = field(default_factory=...)         # AgentMeta
avatars/telemetry.py:24  "no canonical per-agent backend source at HEAD"        # confirms no in-flight signal
threads/__init__.py:88   class ChatThread (participants: list[str]; metadata: dict)  # meeting_active lives here
threads/__init__.py      def list_threads(*, include_archived=False, project_id=None, task_id=None, limit=100)
runtime.py:450       self.chat_thread_store = ChatThreadStore(...)              # public attr
config.py:4600       class CommunicationsConfig(BaseModel)                      # window field home (after AD-928 status_*)
cognitive/introspective_telemetry.py:111  agent.meta.last_active                # precedent recency read
ui/.../CrewRosterPanel.tsx  CrewRow (dept dot + callsign + rank + trust)        # primary dot mount; binds s.crewManifest
ui/.../AgentAvatarBadge.tsx  pure <span> badge, props {agentId,callsign,department?,size?}  # optional presence prop
ui/src/store/useStore.ts:952  openCrewManifest fetch+map idiom to mirror
ui/src/store/types.ts:611     CrewManifestEntry { ..., agentId }                # PresenceState added nearby
ui/.../__tests__/CrewRoster.bridge.test.tsx:29  useStore.setState({ crewManifestOpen, crewManifest })  # BF-287 seed
```
