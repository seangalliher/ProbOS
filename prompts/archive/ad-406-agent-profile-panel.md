# AD-406: Agent Profile Panel

## Overview

Add a floating Agent Profile Panel to the HXI. Clicking an agent orb opens a draggable glass-morphism panel with four tabs: **Chat** (1:1 direct messaging), **Work** (active tasks), **Profile** (personality, rank, department), and **Health** (trust, confidence, memory). Minimized panels show indicators on the orb. Two new API endpoints provide agent profile data and direct chat routing.

## Part 1: Backend — New API Endpoints

### 1a. Agent Profile Endpoint

**File:** `src/probos/api.py`

Add two new endpoints inside `create_app()`. Place them after the existing `/api/notifications/ack-all` endpoint (around line 1000) and before the design endpoints.

```python
# ---------- Agent Profile Panel (AD-406) ----------

class AgentChatRequest(BaseModel):
    """Request to send a direct message to a specific agent."""
    message: str

@app.get("/api/agent/{agent_id}/profile")
async def agent_profile(agent_id: str) -> dict[str, Any]:
    """Get detailed profile for a specific agent."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Basic info
    callsign = ""
    department = ""
    rank = "ensign"
    display_name = ""
    personality: dict[str, float] = {}
    specialization: list[str] = []

    # Crew profile from YAML seed data
    if hasattr(runtime, 'callsign_registry'):
        callsign = runtime.callsign_registry.get_callsign(agent.agent_type)
        resolved = runtime.callsign_registry.resolve(callsign) if callsign else None
        if resolved:
            department = resolved.get("department", "")
            display_name = resolved.get("display_name", "")

    # Load full seed profile for personality
    from probos.crew_profile import load_seed_profile, Rank
    seed = load_seed_profile(agent.agent_type)
    if seed:
        personality = seed.get("personality", {})
        specialization = seed.get("specialization", [])
        display_name = display_name or seed.get("display_name", "")
        department = department or seed.get("department", "")

    # Trust
    trust_score = 0.5
    trust_history: list[float] = []
    if hasattr(runtime, 'trust_network'):
        trust_score = runtime.trust_network.get_score(agent.id)
        rank = Rank.from_trust(trust_score).value
        # Get recent trust history if available
        if hasattr(runtime.trust_network, 'get_history'):
            trust_history = runtime.trust_network.get_history(agent.id, limit=20)

    # Hebbian connections
    hebbian_connections: list[dict[str, Any]] = []
    if hasattr(runtime, 'hebbian_router'):
        for (source, target, rel_type), weight in runtime.hebbian_router.all_weights_typed().items():
            if source == agent.id or target == agent.id:
                other_id = target if source == agent.id else source
                hebbian_connections.append({
                    "targetId": other_id,
                    "weight": round(weight, 4),
                    "relType": rel_type,
                })
        # Sort by weight descending, limit to top 10
        hebbian_connections.sort(key=lambda c: c["weight"], reverse=True)
        hebbian_connections = hebbian_connections[:10]

    # Memory count
    memory_count = 0
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        if hasattr(runtime.episodic_memory, 'count_for_agent'):
            memory_count = await runtime.episodic_memory.count_for_agent(agent.id)

    return {
        "id": agent.id,
        "agentType": agent.agent_type,
        "callsign": callsign,
        "displayName": display_name,
        "rank": rank,
        "department": department,
        "personality": personality,
        "specialization": specialization,
        "trust": round(trust_score, 4),
        "trustHistory": trust_history,
        "confidence": round(agent.confidence, 4),
        "state": agent.state,
        "tier": agent.tier if hasattr(agent, 'tier') else "domain",
        "pool": agent._pool_name if hasattr(agent, '_pool_name') else "",
        "hebbianConnections": hebbian_connections,
        "memoryCount": memory_count,
        "uptime": round(time.time() - (agent._created_at if hasattr(agent, '_created_at') else time.time()), 1),
    }
```

### 1b. Agent Chat Endpoint

```python
@app.post("/api/agent/{agent_id}/chat")
async def agent_chat(agent_id: str, req: AgentChatRequest) -> dict[str, Any]:
    """Send a direct message to a specific agent and get their response."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from probos.types import IntentMessage
    intent = IntentMessage(
        intent="direct_message",
        params={"text": req.message, "from": "hxi_profile", "session": False},
        target_agent_id=agent_id,
    )
    result = await runtime.intent_bus.send(intent)

    callsign = ""
    if hasattr(runtime, 'callsign_registry'):
        callsign = runtime.callsign_registry.get_callsign(agent.agent_type)

    response_text = ""
    if result and result.result:
        response_text = str(result.result)
    elif result and result.error:
        response_text = f"(error: {result.error})"
    else:
        response_text = "(no response)"

    return {
        "response": response_text,
        "callsign": callsign,
        "agentId": agent_id,
    }
```

**Important:** The `AgentChatRequest` model and both endpoints go inside `create_app()` so they have access to the `runtime` closure variable. Match the pattern of existing endpoints.

**Note on `HTTPException`:** Import it at the top of the file alongside the other FastAPI imports — it's cleaner than importing inside each function. Check if it's already imported.

**Note on `agent.tier` and `agent._pool_name`:** Read `src/probos/substrate/agent.py` to see the actual attribute names. Use `agent.info()` if the attributes are private, or access the correct public names. The `callsign` attribute was added in BF-013.

**Note on `trust_network.get_history()`:** This method may not exist. If it doesn't, just return an empty list for `trustHistory`. Don't create the method — it's Phase 2.

**Note on `episodic_memory.count_for_agent()`:** This method may not exist. If it doesn't, return 0. Don't create it — it's Phase 2.

---

## Part 2: Frontend — Store Types

### 2a. New Types

**File:** `ui/src/store/types.ts`

Add these interfaces at the end of the file, before the last blank line:

```typescript
// Agent Profile Panel types (AD-406)

export interface AgentProfileMessage {
  id: string;
  role: 'user' | 'agent';
  text: string;
  timestamp: number;
}

export interface AgentConversation {
  agentId: string;
  messages: AgentProfileMessage[];
  unreadCount: number;
  minimized: boolean;
}

export interface AgentProfileData {
  id: string;
  agentType: string;
  callsign: string;
  displayName: string;
  rank: string;
  department: string;
  personality: Record<string, number>;
  specialization: string[];
  trust: number;
  trustHistory: number[];
  confidence: number;
  state: string;
  tier: string;
  pool: string;
  hebbianConnections: { targetId: string; weight: number; relType: string }[];
  memoryCount: number;
  uptime: number;
}
```

### 2b. Store Extensions

**File:** `ui/src/store/useStore.ts`

**Step 1:** Add the new types to the import statement at line 6:

```typescript
import type {
  Agent, Connection, PoolInfo, PoolGroupInfo, SystemMode, DagNode, ChatMessage, SelfModProposal,
  BuildProposal, BuildFailureReport, ArchitectProposalView, BuildQueueItem, MissionControlTask,
  AgentTaskView, NotificationView,
  AgentProfileMessage, AgentConversation,  // AD-406
  StateSnapshot, TrustUpdateEvent, HebbianUpdateEvent,
  ConsensusEvent, SystemModeEvent, AgentStateEvent, WSEvent,
} from './types';
```

**Step 2:** Add new state fields to the `HXIState` interface (after `pinnedAgent` around line 219):

```typescript
  // Agent Profile Panel (AD-406)
  activeProfileAgent: string | null;
  profilePanelPos: { x: number; y: number };
  agentConversations: Map<string, AgentConversation>;
```

**Step 3:** Add new actions to the `HXIState` interface (after `setPinnedAgent` around line 248):

```typescript
  // Agent Profile Panel actions (AD-406)
  openAgentProfile: (agentId: string) => void;
  closeAgentProfile: () => void;
  minimizeAgentProfile: () => void;
  addAgentMessage: (agentId: string, role: 'user' | 'agent', text: string) => void;
  markAgentRead: (agentId: string) => void;
  setProfilePanelPos: (pos: { x: number; y: number }) => void;
```

**Step 4:** Add initial state values in `create<HXIState>` (after `pinnedAgent: null` around line 331):

```typescript
  // Agent Profile Panel (AD-406)
  activeProfileAgent: null,
  profilePanelPos: { x: 100, y: 100 },
  agentConversations: new Map(),
```

**Step 5:** Add action implementations (after `setPinnedAgent` around line 361):

```typescript
  // Agent Profile Panel actions (AD-406)
  openAgentProfile: (agentId) => set({
    activeProfileAgent: agentId,
    pinnedAgent: null,  // dismiss tooltip when profile opens
  }),
  closeAgentProfile: () => set({ activeProfileAgent: null }),
  minimizeAgentProfile: () => {
    const agentId = get().activeProfileAgent;
    if (!agentId) return;
    const convs = new Map(get().agentConversations);
    const conv = convs.get(agentId);
    if (conv) {
      convs.set(agentId, { ...conv, minimized: true });
    }
    set({ activeProfileAgent: null, agentConversations: convs });
  },
  addAgentMessage: (agentId, role, text) => {
    const convs = new Map(get().agentConversations);
    const existing = convs.get(agentId) || {
      agentId,
      messages: [],
      unreadCount: 0,
      minimized: false,
    };
    const msg: AgentProfileMessage = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      text,
      timestamp: Date.now() / 1000,
    };
    const isOpen = get().activeProfileAgent === agentId;
    convs.set(agentId, {
      ...existing,
      messages: [...existing.messages.slice(-99), msg],
      unreadCount: (role === 'agent' && !isOpen) ? existing.unreadCount + 1 : existing.unreadCount,
      minimized: existing.minimized,
    });
    set({ agentConversations: convs });
  },
  markAgentRead: (agentId) => {
    const convs = new Map(get().agentConversations);
    const conv = convs.get(agentId);
    if (conv) {
      convs.set(agentId, { ...conv, unreadCount: 0, minimized: false });
      set({ agentConversations: convs });
    }
  },
  setProfilePanelPos: (pos) => set({ profilePanelPos: pos }),
```

---

## Part 3: Frontend — Profile Panel Components

### Create directory: `ui/src/components/profile/`

### 3a. Barrel Export

**File:** `ui/src/components/profile/index.ts`

```typescript
export { AgentProfilePanel } from './AgentProfilePanel';
```

### 3b. Agent Profile Panel (main container)

**File:** `ui/src/components/profile/AgentProfilePanel.tsx`

This is the main floating window. It renders a title bar (with drag, minimize, close), a tab bar, and tab content.

```typescript
import { useState, useRef, useCallback, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { ProfileChatTab } from './ProfileChatTab';
import { ProfileWorkTab } from './ProfileWorkTab';
import { ProfileInfoTab } from './ProfileInfoTab';
import { ProfileHealthTab } from './ProfileHealthTab';
import type { AgentProfileData } from '../../store/types';

type ProfileTab = 'chat' | 'work' | 'profile' | 'health';

const TAB_LABELS: { key: ProfileTab; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'work', label: 'Work' },
  { key: 'profile', label: 'Profile' },
  { key: 'health', label: 'Health' },
];

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

export function AgentProfilePanel() {
  const agentId = useStore((s) => s.activeProfileAgent);
  const agents = useStore((s) => s.agents);
  const pos = useStore((s) => s.profilePanelPos);
  const poolToGroup = useStore((s) => s.poolToGroup);

  const [activeTab, setActiveTab] = useState<ProfileTab>('chat');
  const [profileData, setProfileData] = useState<AgentProfileData | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });

  const agent = agentId ? agents.get(agentId) : null;

  // Fetch profile data when agent changes
  useEffect(() => {
    if (!agentId) {
      setProfileData(null);
      return;
    }
    let cancelled = false;
    fetch(`/api/agent/${agentId}/profile`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!cancelled && data) setProfileData(data);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [agentId]);

  // Mark messages read when opening
  useEffect(() => {
    if (agentId) {
      useStore.getState().markAgentRead(agentId);
    }
  }, [agentId]);

  // Drag handlers
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    dragOffset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y };
  }, [pos]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const newX = Math.max(0, Math.min(window.innerWidth - 420, e.clientX - dragOffset.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.current.y));
      useStore.getState().setProfilePanelPos({ x: newX, y: newY });
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  if (!agentId || !agent) return null;

  const callsign = profileData?.callsign || agent.callsign || '';
  const displayName = callsign || agent.agentType;
  const department = profileData?.department || poolToGroup?.[agent.pool] || '';
  const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';

  return (
    <div
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        width: 420,
        height: 580,
        background: 'rgba(10, 10, 18, 0.92)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(240, 176, 96, 0.2)',
        borderRadius: 12,
        zIndex: 25,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#e0dcd4',
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
    >
      {/* Title bar — draggable */}
      <div
        onMouseDown={onMouseDown}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          cursor: isDragging ? 'grabbing' : 'grab',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: deptColor,
          }} />
          <span style={{ fontWeight: 600, fontSize: 14 }}>
            {displayName}
          </span>
          {callsign && (
            <span style={{ color: '#8888a0', fontSize: 12 }}>
              ({agent.agentType})
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={() => useStore.getState().minimizeAgentProfile()}
            style={{
              background: 'none', border: 'none', color: '#8888a0',
              fontSize: 16, cursor: 'pointer', padding: '0 4px',
              lineHeight: 1,
            }}
            title="Minimize"
          >
            &#x2013;
          </button>
          <button
            onClick={() => useStore.getState().closeAgentProfile()}
            style={{
              background: 'none', border: 'none', color: '#8888a0',
              fontSize: 16, cursor: 'pointer', padding: '0 4px',
              lineHeight: 1,
            }}
            title="Close"
          >
            &#x2715;
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        {TAB_LABELS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              borderBottom: activeTab === key ? '2px solid #f0b060' : '2px solid transparent',
              color: activeTab === key ? '#f0b060' : '#8888a0',
              fontSize: 12,
              fontFamily: "'JetBrains Mono', monospace",
              padding: '8px 0',
              cursor: 'pointer',
              transition: 'color 0.15s, border-color 0.15s',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {activeTab === 'chat' && <ProfileChatTab agentId={agentId} />}
        {activeTab === 'work' && <ProfileWorkTab agentId={agentId} />}
        {activeTab === 'profile' && <ProfileInfoTab profileData={profileData} agent={agent} />}
        {activeTab === 'health' && <ProfileHealthTab profileData={profileData} agent={agent} />}
      </div>
    </div>
  );
}
```

### 3c. Chat Tab

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

1:1 messaging with the agent. Messages stored in `agentConversations`.

```typescript
import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';

interface Props {
  agentId: string;
}

export function ProfileChatTab({ agentId }: Props) {
  const conversation = useStore((s) => s.agentConversations.get(agentId));
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const messages = conversation?.messages ?? [];

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setSending(true);

    // Add user message immediately
    useStore.getState().addAgentMessage(agentId, 'user', text);

    try {
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      useStore.getState().addAgentMessage(agentId, 'agent', data.response || '(no response)');
    } catch {
      useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
      setSending(false);
    }
  }, [agentId, input, sending]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Message list */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '8px 12px',
      }}>
        {messages.length === 0 && (
          <div style={{ color: '#555568', fontSize: 12, textAlign: 'center', marginTop: 40 }}>
            Send a message to start a conversation.
          </div>
        )}
        {messages.map(msg => (
          <div
            key={msg.id}
            style={{
              marginBottom: 8,
              textAlign: msg.role === 'user' ? 'right' : 'left',
            }}
          >
            <div style={{
              display: 'inline-block',
              maxWidth: '85%',
              padding: '6px 10px',
              borderRadius: 8,
              fontSize: 12,
              lineHeight: 1.5,
              background: msg.role === 'user'
                ? 'rgba(240, 176, 96, 0.15)'
                : 'rgba(255, 255, 255, 0.05)',
              border: msg.role === 'user'
                ? '1px solid rgba(240, 176, 96, 0.2)'
                : '1px solid rgba(255, 255, 255, 0.06)',
              color: '#e0dcd4',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {msg.text}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{
        display: 'flex',
        gap: 6,
        padding: '8px 12px',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message..."
          disabled={sending}
          style={{
            flex: 1,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 6,
            color: '#e0dcd4',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '6px 10px',
            outline: 'none',
          }}
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          style={{
            background: sending ? 'rgba(240, 176, 96, 0.1)' : 'rgba(240, 176, 96, 0.2)',
            border: '1px solid rgba(240, 176, 96, 0.3)',
            borderRadius: 6,
            color: '#f0b060',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '6px 12px',
            cursor: sending ? 'default' : 'pointer',
            opacity: sending || !input.trim() ? 0.5 : 1,
          }}
        >
          {sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}
```

### 3d. Work Tab

**File:** `ui/src/components/profile/ProfileWorkTab.tsx`

Shows active tasks assigned to this agent, filtered from `agentTasks`.

```typescript
import { useStore } from '../../store/useStore';

const STATUS_COLORS: Record<string, string> = {
  working: '#50b0a0',
  review: '#f0b060',
  queued: '#8888a0',
  done: '#80c878',
  failed: '#d05050',
};

function formatElapsed(startedAt: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

interface Props {
  agentId: string;
}

export function ProfileWorkTab({ agentId }: Props) {
  const agentTasks = useStore((s) => s.agentTasks);

  const tasks = (agentTasks ?? []).filter(t => t.agent_id === agentId);

  if (tasks.length === 0) {
    return (
      <div style={{ color: '#555568', fontSize: 12, textAlign: 'center', marginTop: 40, padding: '0 20px' }}>
        No active tasks assigned to this agent.
      </div>
    );
  }

  return (
    <div style={{ padding: '8px 12px', overflowY: 'auto', height: '100%' }}>
      {tasks.map(task => (
        <div key={task.id} style={{
          marginBottom: 8,
          padding: '8px 10px',
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 6,
          fontSize: 12,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontWeight: 600, color: '#c8d0e0' }}>
              {task.title.length > 40 ? task.title.slice(0, 40) + '\u2026' : task.title}
            </span>
            <span style={{ color: STATUS_COLORS[task.status] || '#8888a0', fontSize: 10 }}>
              {task.status}
            </span>
          </div>
          {task.step_total > 0 && (
            <div style={{ color: '#8888a0', fontSize: 10, marginBottom: 4 }}>
              Step {task.step_current} of {task.step_total}
              {task.steps?.[task.step_current - 1]?.label && `: ${task.steps[task.step_current - 1].label}`}
            </div>
          )}
          {task.started_at > 0 && (
            <div style={{ color: '#666680', fontSize: 10 }}>
              Elapsed: {formatElapsed(task.started_at)}
            </div>
          )}
          {task.step_total > 0 && (
            <div style={{
              height: 3, borderRadius: 2,
              background: 'rgba(255,255,255,0.06)',
              marginTop: 4, overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${(task.step_current / task.step_total) * 100}%`,
                background: STATUS_COLORS[task.status] || '#5090d0',
                borderRadius: 2,
                transition: 'width 0.3s ease',
              }} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

### 3e. Profile Info Tab

**File:** `ui/src/components/profile/ProfileInfoTab.tsx`

Shows personality traits (Big Five bars), rank, department, specialization, Hebbian connections.

```typescript
import type { Agent, AgentProfileData } from '../../store/types';

const TRAIT_LABELS: Record<string, string> = {
  openness: 'Openness',
  conscientiousness: 'Conscientious',
  extraversion: 'Extraversion',
  agreeableness: 'Agreeableness',
  neuroticism: 'Neuroticism',
};

const TRAIT_COLORS: Record<string, string> = {
  openness: '#50b0a0',
  conscientiousness: '#5090d0',
  extraversion: '#f0b060',
  agreeableness: '#80c878',
  neuroticism: '#d05050',
};

const RANK_LABELS: Record<string, string> = {
  ensign: 'Ensign',
  lieutenant: 'Lieutenant',
  commander: 'Commander',
  senior_officer: 'Senior Officer',
};

interface Props {
  profileData: AgentProfileData | null;
  agent: Agent;
}

export function ProfileInfoTab({ profileData, agent }: Props) {
  if (!profileData) {
    return (
      <div style={{ color: '#555568', fontSize: 12, textAlign: 'center', marginTop: 40 }}>
        Loading profile...
      </div>
    );
  }

  const personality = profileData.personality || {};
  const traits = Object.entries(personality).filter(
    ([key]) => key in TRAIT_LABELS
  );

  return (
    <div style={{ padding: '12px 14px', overflowY: 'auto', height: '100%', fontSize: 12 }}>
      {/* Identity */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Identity
        </div>
        <div>
          <span style={{ color: '#8888a0' }}>Rank: </span>
          <span style={{ color: '#e0dcd4' }}>
            {RANK_LABELS[profileData.rank] || profileData.rank}
          </span>
        </div>
        {profileData.department && (
          <div>
            <span style={{ color: '#8888a0' }}>Department: </span>
            <span style={{ color: '#e0dcd4', textTransform: 'capitalize' }}>
              {profileData.department}
            </span>
          </div>
        )}
        {profileData.displayName && profileData.displayName !== profileData.callsign && (
          <div>
            <span style={{ color: '#8888a0' }}>Role: </span>
            <span style={{ color: '#e0dcd4' }}>{profileData.displayName}</span>
          </div>
        )}
        {profileData.specialization.length > 0 && (
          <div>
            <span style={{ color: '#8888a0' }}>Specialization: </span>
            <span style={{ color: '#e0dcd4' }}>{profileData.specialization.join(', ')}</span>
          </div>
        )}
      </div>

      {/* Personality — Big Five bars */}
      {traits.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 6 }}>
            Personality
          </div>
          {traits.map(([key, value]) => (
            <div key={key} style={{ marginBottom: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ color: '#8888a0', fontSize: 11 }}>{TRAIT_LABELS[key]}</span>
                <span style={{ color: '#666680', fontSize: 10 }}>{Math.round((value as number) * 100)}%</span>
              </div>
              <div style={{
                height: 4, borderRadius: 2,
                background: 'rgba(255,255,255,0.06)',
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${(value as number) * 100}%`,
                  background: TRAIT_COLORS[key] || '#5090d0',
                  borderRadius: 2,
                }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Hebbian connections */}
      {profileData.hebbianConnections.length > 0 && (
        <div>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Connections
          </div>
          {profileData.hebbianConnections.map((conn, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between',
              padding: '2px 0', fontSize: 11,
            }}>
              <span style={{ color: '#e0dcd4', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {conn.targetId.slice(0, 12)}...
              </span>
              <span style={{ color: '#8888a0' }}>
                {conn.weight.toFixed(3)} ({conn.relType})
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 3f. Health Tab

**File:** `ui/src/components/profile/ProfileHealthTab.tsx`

Trust, confidence, memory count, uptime, state.

```typescript
import type { Agent, AgentProfileData } from '../../store/types';

interface Props {
  profileData: AgentProfileData | null;
  agent: Agent;
}

export function ProfileHealthTab({ profileData, agent }: Props) {
  const trust = profileData?.trust ?? agent.trust;
  const confidence = profileData?.confidence ?? agent.confidence;
  const trustColor = trust >= 0.7 ? '#f0b060' : trust >= 0.35 ? '#88a4c8' : '#7060a8';
  const stateColor = agent.state === 'active' ? '#80c878' : '#f0b060';

  function formatUptime(seconds: number): string {
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    const min = Math.floor(seconds / 60);
    if (min < 60) return `${min}m`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ${min % 60}m`;
    const days = Math.floor(hr / 24);
    return `${days}d ${hr % 24}h`;
  }

  return (
    <div style={{ padding: '12px 14px', overflowY: 'auto', height: '100%', fontSize: 12 }}>
      {/* Trust */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Trust
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 24, fontWeight: 600, color: trustColor }}>
            {(trust * 100).toFixed(0)}%
          </span>
          <span style={{ color: '#666680', fontSize: 11 }}>
            {trust >= 0.7 ? 'high' : trust >= 0.35 ? 'medium' : 'low'}
          </span>
        </div>
        {/* Trust history sparkline */}
        {profileData?.trustHistory && profileData.trustHistory.length > 1 && (
          <svg width="100%" height={30} style={{ marginTop: 4 }}>
            {(() => {
              const vals = profileData.trustHistory;
              const min = Math.min(...vals) * 0.95;
              const max = Math.max(...vals) * 1.05 || 1;
              const w = 380;
              const h = 28;
              const points = vals.map((v, i) => {
                const x = (i / (vals.length - 1)) * w;
                const y = h - ((v - min) / (max - min)) * h;
                return `${x},${y}`;
              }).join(' ');
              return <polyline points={points} fill="none" stroke={trustColor} strokeWidth={1.5} opacity={0.6} />;
            })()}
          </svg>
        )}
      </div>

      {/* Confidence */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Confidence
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            flex: 1, height: 6, borderRadius: 3,
            background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
          }}>
            <div style={{
              height: '100%',
              width: `${confidence * 100}%`,
              background: '#5090d0',
              borderRadius: 3,
            }} />
          </div>
          <span style={{ color: '#e0dcd4', fontSize: 12 }}>
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* State */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Status
        </div>
        <span style={{ color: stateColor, textTransform: 'capitalize' }}>{agent.state}</span>
      </div>

      {/* Memory count */}
      {profileData && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Episodic Memory
          </div>
          <span style={{ color: '#e0dcd4' }}>
            {profileData.memoryCount} episode{profileData.memoidCount !== 1 ? 's' : ''}
          </span>
        </div>
      )}

      {/* Uptime */}
      {profileData && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Uptime
          </div>
          <span style={{ color: '#e0dcd4' }}>{formatUptime(profileData.uptime)}</span>
        </div>
      )}

      {/* Agent ID */}
      <div>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Agent ID
        </div>
        <span style={{ color: '#555568', fontSize: 10, wordBreak: 'break-all' }}>
          {agent.id}
        </span>
      </div>
    </div>
  );
}
```

**Note:** There is a typo in the code above — `profileData.memoidCount` should be `profileData.memoryCount`. Fix this when implementing.

---

## Part 4: Wire Into App and Canvas

### 4a. Render Profile Panel in App

**File:** `ui/src/App.tsx`

Add the import and render the `AgentProfilePanel` inside the root div:

```typescript
import { AgentProfilePanel } from './components/profile';

// In the return statement, add after <AgentTooltip />:
<AgentProfilePanel />
```

### 4b. Change Orb Click to Open Profile

**File:** `ui/src/components/CognitiveCanvas.tsx`

In the `handleClick` callback inside `AgentRaycastLayer`, change `setPinnedAgent` to `openAgentProfile`:

```typescript
const handleClick = useCallback((e: ThreeEvent<MouseEvent>) => {
  if (e.instanceId !== undefined && e.instanceId < agentListRef.current.length) {
    const agent = agentListRef.current[e.instanceId];
    useStore.getState().openAgentProfile(agent.id);
  } else {
    // Click on empty space — close profile if open
    const store = useStore.getState();
    if (store.activeProfileAgent) {
      store.closeAgentProfile();
    }
  }
  e.stopPropagation();
}, []);
```

### 4c. Suppress Tooltip When Profile Open

**File:** `ui/src/components/AgentTooltip.tsx`

Add a check at the top of the component to hide the tooltip when the profile panel is showing for that agent:

```typescript
export function AgentTooltip() {
  const hovered = useStore((s) => s.hoveredAgent);
  const pinned = useStore((s) => s.pinnedAgent);
  const activeProfileAgent = useStore((s) => s.activeProfileAgent);  // AD-406
  const pos = useStore((s) => s.tooltipPos);
  // ...

  const agent = pinned || hovered;
  if (!agent) return null;

  // Suppress tooltip when profile panel is showing (AD-406)
  if (activeProfileAgent) return null;

  // ... rest unchanged
```

This hides the tooltip entirely while any profile panel is open. Simple and avoids visual overlap.

### 4d. Orb Visual Indicators

**File:** `ui/src/canvas/agents.tsx`

In the `useFrame` callback, after the existing attention pulse logic (around line 92-98), add conversation indicators. Read the `agentConversations` from the store at the top of the `useFrame` callback alongside `tasks`:

```typescript
// Inside useFrame, alongside the existing tasks read:
const agentConversations = useStore.getState().agentConversations;
const activeProfileAgent = useStore.getState().activeProfileAgent;

// Then, inside the agentList.forEach loop, after the attention pulse block:

// Profile panel indicators (AD-406)
const conv = agentConversations.get(agent.id);
const isProfileOpen = activeProfileAgent === agent.id;

if (isProfileOpen && connected) {
  // Active conversation — steady amber glow
  const amberMix = 0.3;
  _tempColor.r = _tempColor.r * (1 - amberMix) + 0.94 * amberMix;
  _tempColor.g = _tempColor.g * (1 - amberMix) + 0.69 * amberMix;
  _tempColor.b = _tempColor.b * (1 - amberMix) + 0.38 * amberMix;
} else if (conv?.minimized && conv.unreadCount > 0 && connected) {
  // Minimized with unread — fast pulse (3Hz)
  const pulse = 0.3 + 0.3 * Math.sin(t * 6 * Math.PI);
  _tempColor.r = _tempColor.r * (1 - pulse) + 0.94 * pulse;
  _tempColor.g = _tempColor.g * (1 - pulse) + 0.69 * pulse;
  _tempColor.b = _tempColor.b * (1 - pulse) + 0.38 * pulse;
} else if (conv?.minimized && connected) {
  // Minimized no unread — gentle pulse (1Hz)
  const pulse = 0.1 + 0.1 * Math.sin(t * 2 * Math.PI);
  _tempColor.r = _tempColor.r * (1 - pulse) + 0.94 * pulse;
  _tempColor.g = _tempColor.g * (1 - pulse) + 0.69 * pulse;
  _tempColor.b = _tempColor.b * (1 - pulse) + 0.38 * pulse;
}
```

---

## Part 5: Testing

### 5a. Backend Tests

**File:** `tests/test_api.py` (or create `tests/test_api_profile.py` if `test_api.py` doesn't exist or is too large)

```python
"""Tests for Agent Profile Panel API endpoints (AD-406)."""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    agent = MagicMock()
    agent.id = "agent-123"
    agent.agent_type = "scout"
    agent.confidence = 0.85
    agent.state = "active"
    agent.tier = "domain"
    agent._pool_name = "scout"
    agent._created_at = time.time() - 3600
    agent.callsign = "Wesley"
    agent.is_alive = True
    return agent


@pytest.fixture
def mock_runtime(mock_agent):
    """Create a mock runtime with necessary services."""
    runtime = MagicMock()
    runtime.registry.get.return_value = mock_agent
    runtime.registry.all.return_value = [mock_agent]

    # Callsign registry
    runtime.callsign_registry.get_callsign.return_value = "Wesley"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Wesley",
        "agent_type": "scout",
        "agent_id": "agent-123",
        "display_name": "Science Officer",
        "department": "science",
    }

    # Trust network
    runtime.trust_network.get_score.return_value = 0.82

    # Hebbian router
    runtime.hebbian_router.all_weights_typed.return_value = {
        ("agent-123", "agent-456", "routing"): 0.75,
    }

    # No episodic memory
    runtime.episodic_memory = None

    # Intent bus for chat
    result = MagicMock()
    result.result = "Hello Captain, reporting for duty."
    result.success = True
    result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=result)

    # Event listener (needed for create_app)
    runtime.add_event_listener = MagicMock()

    return runtime


@pytest.fixture
def client(mock_runtime):
    """Create a test client for the API."""
    from probos.api import create_app
    from fastapi.testclient import TestClient
    app = create_app(mock_runtime)
    return TestClient(app)


def test_agent_profile_returns_data(client, mock_runtime):
    """GET /api/agent/{id}/profile returns agent profile data."""
    resp = client.get("/api/agent/agent-123/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "agent-123"
    assert data["agentType"] == "scout"
    assert data["callsign"] == "Wesley"
    assert data["department"] == "science"
    assert isinstance(data["trust"], float)
    assert isinstance(data["hebbianConnections"], list)


def test_agent_profile_404_unknown(client, mock_runtime):
    """GET /api/agent/{id}/profile returns 404 for unknown agent."""
    mock_runtime.registry.get.return_value = None
    resp = client.get("/api/agent/unknown-id/profile")
    assert resp.status_code == 404


def test_agent_chat_sends_message(client, mock_runtime):
    """POST /api/agent/{id}/chat routes direct_message intent."""
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "Status report, Wesley"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert data["callsign"] == "Wesley"
    assert data["agentId"] == "agent-123"
    # Verify intent was sent
    mock_runtime.intent_bus.send.assert_called_once()


def test_agent_chat_404_unknown(client, mock_runtime):
    """POST /api/agent/{id}/chat returns 404 for unknown agent."""
    mock_runtime.registry.get.return_value = None
    resp = client.post(
        "/api/agent/unknown-id/chat",
        json={"message": "Hello"},
    )
    assert resp.status_code == 404
```

### 5b. Frontend Tests

**File:** `ui/src/__tests__/AgentProfilePanel.test.tsx` (or add to existing test file)

Write vitest tests for:

1. **AgentProfilePanel renders when activeProfileAgent is set** — Set `activeProfileAgent` in store, verify panel renders with correct title
2. **Tab switching works** — Click each tab button, verify content changes
3. **Chat message submission** — Type text, press Enter or click Send, verify `addAgentMessage` is called
4. **Minimize stores conversation state** — Click minimize, verify `minimizeAgentProfile` sets correct state
5. **Close clears state** — Click close, verify `activeProfileAgent` becomes null
6. **Panel hidden when no agent selected** — activeProfileAgent null → nothing renders

Read the existing test files to match the testing patterns already used in the codebase.

---

## Files Created/Modified

| File | Change |
|------|--------|
| `src/probos/api.py` | Add `GET /api/agent/{id}/profile` and `POST /api/agent/{id}/chat` endpoints |
| `ui/src/store/types.ts` | Add `AgentProfileMessage`, `AgentConversation`, `AgentProfileData` interfaces |
| `ui/src/store/useStore.ts` | Add profile panel state + 6 new actions |
| `ui/src/components/profile/index.ts` | **NEW** — barrel export |
| `ui/src/components/profile/AgentProfilePanel.tsx` | **NEW** — main floating panel container |
| `ui/src/components/profile/ProfileChatTab.tsx` | **NEW** — 1:1 chat tab |
| `ui/src/components/profile/ProfileWorkTab.tsx` | **NEW** — work items tab |
| `ui/src/components/profile/ProfileInfoTab.tsx` | **NEW** — personality/rank/connections tab |
| `ui/src/components/profile/ProfileHealthTab.tsx` | **NEW** — trust/confidence/health tab |
| `ui/src/App.tsx` | Import and render `AgentProfilePanel` |
| `ui/src/components/CognitiveCanvas.tsx` | Change click handler from `setPinnedAgent` to `openAgentProfile` |
| `ui/src/components/AgentTooltip.tsx` | Suppress tooltip when profile panel is open |
| `ui/src/canvas/agents.tsx` | Add orb visual indicators for conversations |
| `tests/test_api_profile.py` | **NEW** — backend tests for profile endpoints |
| `ui/src/__tests__/AgentProfilePanel.test.tsx` | **NEW** — frontend tests |

## Implementation Order

1. Backend endpoints first (api.py) — they're independent
2. Store types and actions (types.ts, useStore.ts) — foundation for components
3. Profile panel components (profile/ directory)
4. Wire into App, CognitiveCanvas, AgentTooltip, agents.tsx
5. Tests (backend then frontend)
6. Verify build: `cd ui && npx vitest run` and `uv run pytest tests/ --tb=short`

## What NOT to Build

- **Multi-panel** — only one profile panel at a time
- **Agent-to-agent chat forwarding** — separate Ward Room AD
- **Trust history chart** — sparkline only in Phase 1
- **Persistent conversations** — session memory only, no disk
- **Profile editing** — read-only view
- **`trust_network.get_history()`** — return empty list if method doesn't exist
- **`episodic_memory.count_for_agent()`** — return 0 if method doesn't exist

## Testing

```bash
# Backend
uv run pytest tests/test_api_profile.py -v

# Frontend
cd ui && npx vitest run --reporter=verbose

# Full regression
uv run pytest tests/ --tb=short -q
```

## Commit Message

```
Add Agent Profile Panel with 1:1 chat and crew details (AD-406)

Click agent orb to open floating profile panel with Chat, Work,
Profile, and Health tabs. New API endpoints for agent profile data
and direct messaging. Orb indicators for active/minimized conversations.
Glass morphism styling consistent with existing HXI components.
```
