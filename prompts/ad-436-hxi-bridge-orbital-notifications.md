# AD-436: HXI Bridge System Panel + Orbital Notification Redesign

**Goal:** Two improvements in one AD: (1) Add a "System" section to the Bridge panel with service status, shutdown controls, and thread management. (2) Replace invisible torus notification rings with orbiting electron dots visible outside the agent orbs.

**Scope:** Medium. 2 backend endpoints, 1 new frontend component, 1 modified frontend component, 1 canvas rewrite section, 1 type addition.

---

## Step 1: Backend — System Endpoints

**File: `src/probos/api.py`**

### 1a. Add Pydantic model

After the existing `EndorseRequest` class (line ~220), add:

```python
class ShutdownRequest(BaseModel):
    reason: str = ""
```

### 1b. Add `GET /api/system/services` endpoint

Place this after the `@app.get("/api/tasks")` endpoint (after line ~364), inside `create_app()`:

```python
@app.get("/api/system/services")
async def system_services() -> dict[str, Any]:
    """AD-436: Service status for Bridge System panel."""
    services = []
    checks = [
        ("Ward Room", runtime.ward_room),
        ("Episodic Memory", runtime.episodic_memory),
        ("Trust Network", runtime.trust_network),
        ("Knowledge Store", getattr(runtime, '_knowledge_store', None)),
        ("Cognitive Journal", getattr(runtime, 'cognitive_journal', None)),
        ("Codebase Index", getattr(runtime, 'codebase_index', None)),
        ("Skill Framework", getattr(runtime, 'skill_registry', None)),
        ("Skill Service", getattr(runtime, 'skill_service', None)),
        ("ACM", getattr(runtime, 'acm', None)),
        ("Hebbian Router", getattr(runtime, 'hebbian_router', None)),
        ("Intent Bus", getattr(runtime, 'intent_bus', None)),
    ]
    for name, svc in checks:
        if svc is None:
            status = "offline"
        else:
            status = "online"
        services.append({"name": name, "status": status})
    return {"services": services}
```

### 1c. Add `POST /api/system/shutdown` endpoint

Place this right after the services endpoint:

```python
@app.post("/api/system/shutdown")
async def system_shutdown(req: ShutdownRequest) -> dict[str, Any]:
    """AD-436: Initiate system shutdown from HXI Bridge."""
    async def _do_shutdown():
        await asyncio.sleep(1)  # Let response return first
        await runtime.stop(reason=req.reason)
    _track_task(_do_shutdown(), name="system-shutdown")
    return {"status": "shutting_down", "reason": req.reason}
```

**Key points:**
- `_do_shutdown()` sleeps 1s before calling `runtime.stop()` so the HTTP response returns to the client first
- Uses existing `_track_task` for lifecycle management
- `runtime.stop(reason=...)` already has the AD-435 reason parameter

---

## Step 2: Frontend — Bridge System Component

### 2a. New file: `ui/src/components/bridge/BridgeSystem.tsx`

```tsx
/* Bridge System Panel — service status, shutdown, thread management (AD-436) */

import { useState, useEffect, useCallback } from 'react';

interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'degraded';
}

interface ThreadSummary {
  id: string;
  title: string;
  author_callsign: string;
  locked: boolean;
  reply_count: number;
  channel_name: string;
}

/* ── Service Status List ── */
function ServiceStatusList() {
  const [services, setServices] = useState<ServiceStatus[]>([]);

  const fetchServices = useCallback(async () => {
    try {
      const res = await fetch('/api/system/services');
      const data = await res.json();
      setServices(data.services || []);
    } catch { /* swallow */ }
  }, []);

  useEffect(() => {
    fetchServices();
    const interval = setInterval(fetchServices, 10000);
    return () => clearInterval(interval);
  }, [fetchServices]);

  const statusDot = (s: string) => {
    const color = s === 'online' ? '#50d070' : s === 'degraded' ? '#f0b060' : '#f04040';
    return (
      <span style={{
        display: 'inline-block', width: 6, height: 6,
        borderRadius: '50%', background: color, marginRight: 6,
      }} />
    );
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px' }}>
      {services.map(s => (
        <div key={s.name} style={{
          fontSize: 9, color: '#aaa', padding: '2px 0',
          display: 'flex', alignItems: 'center',
        }}>
          {statusDot(s.status)}
          {s.name}
        </div>
      ))}
    </div>
  );
}

/* ── Shutdown Control ── */
function ShutdownControl() {
  const [reason, setReason] = useState('');
  const [confirming, setConfirming] = useState(false);

  const handleShutdown = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    try {
      await fetch('/api/system/shutdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
    } catch { /* swallow */ }
    setConfirming(false);
  };

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
      <input
        type="text"
        placeholder="Shutdown reason..."
        value={reason}
        onChange={e => setReason(e.target.value)}
        style={{
          flex: 1, background: 'rgba(255,255,255,0.05)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: 4, padding: '4px 8px',
          color: '#ccc', fontSize: 10,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      />
      <button
        onClick={handleShutdown}
        onBlur={() => setTimeout(() => setConfirming(false), 200)}
        style={{
          background: confirming ? '#c02020' : 'rgba(200,40,40,0.2)',
          border: confirming ? '1px solid #f04040' : '1px solid rgba(200,40,40,0.3)',
          borderRadius: 4, padding: '4px 10px',
          color: confirming ? '#fff' : '#f08080',
          fontSize: 9, cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 700, letterSpacing: 1,
          textTransform: 'uppercase' as const,
        }}
      >
        {confirming ? 'CONFIRM' : 'SHUTDOWN'}
      </button>
    </div>
  );
}

/* ── Thread Management ── */
function ThreadManagement() {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchThreads = useCallback(async () => {
    try {
      const res = await fetch('/api/wardroom/activity?limit=10&sort=recent');
      const data = await res.json();
      setThreads((data.threads || []).map((t: any) => ({
        id: t.id,
        title: t.title,
        author_callsign: t.author_callsign || t.author_id,
        locked: t.locked,
        reply_count: t.reply_count,
        channel_name: t.channel_name || '',
      })));
    } catch { /* swallow */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchThreads(); }, [fetchThreads]);

  const toggleLock = async (threadId: string, currently: boolean) => {
    try {
      await fetch(`/api/wardroom/threads/${threadId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ locked: !currently }),
      });
      setThreads(prev => prev.map(t =>
        t.id === threadId ? { ...t, locked: !currently } : t
      ));
    } catch { /* swallow */ }
  };

  if (loading) return <div style={{ fontSize: 9, color: '#555' }}>Loading...</div>;
  if (threads.length === 0) return <div style={{ fontSize: 9, color: '#555', fontStyle: 'italic' }}>No threads</div>;

  return (
    <div>
      {threads.map(t => (
        <div key={t.id} style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <span style={{ fontSize: 9, color: '#888', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <span style={{ color: '#666' }}>{t.channel_name ? `${t.channel_name}/` : ''}</span>
            {t.title}
            <span style={{ color: '#555', marginLeft: 4 }}>({t.reply_count})</span>
          </span>
          <button
            onClick={() => toggleLock(t.id, t.locked)}
            title={t.locked ? 'Unlock thread' : 'Lock thread'}
            style={{
              background: 'none', border: 'none',
              color: t.locked ? '#f0b060' : '#555',
              cursor: 'pointer', fontSize: 11, padding: '0 2px',
            }}
          >
            {t.locked ? '\u{1F512}' : '\u{1F513}'}
          </button>
        </div>
      ))}
    </div>
  );
}

/* ── Exported composite ── */
export function BridgeSystem() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>SERVICES</div>
        <ServiceStatusList />
      </div>
      <div>
        <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>THREADS</div>
        <ThreadManagement />
      </div>
      <div>
        <div style={{ fontSize: 9, color: '#666', marginBottom: 2, fontWeight: 600 }}>SHUTDOWN</div>
        <ShutdownControl />
      </div>
    </div>
  );
}
```

### 2b. Modify `ui/src/components/BridgePanel.tsx`

**Import BridgeSystem** — add at line 7 (after existing bridge imports):

```typescript
import { BridgeSystem } from './bridge/BridgeSystem';
```

**Add System section** — insert right before the `{/* ATTENTION */}` comment (line ~162), inside the scrollable content div:

```tsx
{/* SYSTEM (AD-436) */}
<BridgeSection title="System" count={0} defaultOpen={false} accentColor="#70a0d0">
  <BridgeSystem />
</BridgeSection>
```

The `count={0}` is fine — `BridgeSection` already handles `(0)` display gracefully. The System section is always visible since it's the ship's control panel.

---

## Step 3: Orbital Notification Redesign

**File: `ui/src/canvas/agents.tsx`**

Replace the torus-ring notification system with orbiting electron dots. The notification logic (which tier, what color, when to show) stays the same — only the geometry and animation changes.

### 3a. Replace ring geometry and instancing

**Change the ring instanced mesh** (lines ~242-258). Replace:

```tsx
{/* Priority ring indicators: red (error/action) > amber (chat) > cyan (info) */}
<instancedMesh
  key={`rings-${count}`}
  ref={ringRef}
  args={[undefined, undefined, count]}
  raycast={() => null}
>
  <torusGeometry args={[1, 0.04, 8, 32]} />
  <meshBasicMaterial
    toneMapped={false}
    transparent
    opacity={0.8}
  />
  <instancedBufferAttribute
    attach="instanceColor"
    args={[ringColors, 3]}
  />
</instancedMesh>
```

With:

```tsx
{/* Orbital electron notification dots (AD-436) */}
<instancedMesh
  key={`electrons-${count}`}
  ref={ringRef}
  args={[undefined, undefined, count * 6]}
  raycast={() => null}
>
  <sphereGeometry args={[1, 8, 8]} />
  <meshBasicMaterial
    toneMapped={false}
    transparent
    opacity={0.9}
  />
  <instancedBufferAttribute
    attach="instanceColor"
    args={[ringColors, 3]}
  />
</instancedMesh>
```

**Note:** `count * 6` instances (6 electrons max per agent: 2 per tier, 3 tiers). Reuses `ringRef` and `ringColors` names.

### 3b. Update ringColors buffer size

Change the `ringColors` useMemo (lines ~41-49):

```typescript
const ringColors = useMemo(() => {
  const arr = new Float32Array(Math.max(count * 6, 1) * 3);
  // Initialize all to zero (hidden electrons start black)
  return arr;
}, [count]);
```

### 3c. Update useEffect ring initialization

In the `useEffect` (lines ~67-75), change the ring initialization loop to handle `count * 6` instances:

```typescript
const ring = ringRef.current;
if (ring) {
  for (let i = 0; i < count * 6; i++) {
    _ringObj.scale.setScalar(0);
    _ringObj.updateMatrix();
    ring.setMatrixAt(i, _ringObj.matrix);
  }
  ring.instanceMatrix.needsUpdate = true;
}
```

### 3d. Add orbital math helpers

At the top of the file (after line 11, after the `_ringColor` declaration), add:

```typescript
// AD-436: Orbital notification electron math
const _electronEulers = [
  new THREE.Euler(0.35, 0, 0),           // Tier 0 (RED): 20° tilt
  new THREE.Euler(1.05, 0.52, 0),        // Tier 1 (AMBER): 60° + 30° tilt
  new THREE.Euler(-0.52, 1.05, 0),       // Tier 2 (CYAN): -30° + 60° tilt
];
const _orbitQuat = new THREE.Quaternion();
const _orbitVec = new THREE.Vector3();

const GOLDEN_ANGLE = 2.399963; // 137.5° in radians — prevents visual clustering
```

### 3e. Replace ring animation block in useFrame

Replace the ring indicator block inside `useFrame` (lines ~149-205 in the current code, the `// Priority ring indicator (AD-406)` section). The entire `if (ring && connected) { ... }` block for the current agent becomes:

```typescript
// AD-436: Orbital electron notification dots
// For each agent, populate up to 6 electron instances (2 per tier, 3 tiers)
// Instance index = agentIndex * 6 + tierIndex * 2 + dotIndex
if (ring && connected) {
  const conv = agentConversations.get(agent.id);
  const isProfileOpen = activeProfileAgent === agent.id;
  const hasError = agentErrorNotifs.has(agent.id) || needsAttention;
  const hasConv = isProfileOpen || conv?.minimized;
  const hasInfo = agentInfoNotifs.has(agent.id);

  // Determine active tiers and their params
  const tiers: Array<{
    active: boolean;
    dots: number;
    r: number; g: number; b: number;
    orbitRadius: number;
    speed: number;
    pulse: boolean;
  }> = [
    // Tier 0: RED (error/action)
    {
      active: hasError,
      dots: hasError ? 2 : 0,
      r: RED_R, g: RED_G, b: RED_B,
      orbitRadius: baseSize * 1.3,
      speed: 3,  // 3 rev/s
      pulse: true,
    },
    // Tier 1: AMBER (conversation)
    {
      active: hasConv,
      dots: hasConv ? 2 : 0,
      r: AMBER_R, g: AMBER_G, b: AMBER_B,
      orbitRadius: baseSize * 1.6,
      speed: (conv?.minimized && conv.unreadCount > 0) ? 3 : 0.5,
      pulse: false,
    },
    // Tier 2: CYAN (info)
    {
      active: hasInfo,
      dots: hasInfo ? 2 : 0,
      r: CYAN_R, g: CYAN_G, b: CYAN_B,
      orbitRadius: baseSize * 1.9,
      speed: 0.5,
      pulse: false,
    },
  ];

  for (let tier = 0; tier < 3; tier++) {
    const cfg = tiers[tier];
    for (let dot = 0; dot < 2; dot++) {
      const instanceIdx = i * 6 + tier * 2 + dot;

      if (cfg.active && dot < cfg.dots) {
        // Phase offset: golden angle per agent + 180° between dots
        const phase = i * GOLDEN_ANGLE + dot * Math.PI;
        const angle = t * cfg.speed * 2 * Math.PI + phase;

        // Circular orbit in XZ plane
        _orbitVec.set(
          Math.cos(angle) * cfg.orbitRadius,
          0,
          Math.sin(angle) * cfg.orbitRadius,
        );

        // Apply tier-specific tilt
        _orbitQuat.setFromEuler(_electronEulers[tier]);
        _orbitVec.applyQuaternion(_orbitQuat);

        // Translate to agent world position
        _ringObj.position.set(
          agent.position[0] + _orbitVec.x,
          agent.position[1] + _orbitVec.y,
          agent.position[2] + _orbitVec.z,
        );

        // Electron scale — pulse for RED tier
        const electronScale = cfg.pulse
          ? 0.12 + 0.06 * Math.sin(t * 8)
          : 0.15;
        _ringObj.scale.setScalar(electronScale);
        _ringObj.updateMatrix();
        ring.setMatrixAt(instanceIdx, _ringObj.matrix);

        // Dim amber when no unread
        const dimFactor = (tier === 1 && !(conv?.minimized && conv.unreadCount > 0)) ? 0.6 : 1.0;
        _ringColor.setRGB(cfg.r * dimFactor, cfg.g * dimFactor, cfg.b * dimFactor);
        ring.setColorAt(instanceIdx, _ringColor);
      } else {
        // Hide: scale to 0
        _ringObj.scale.setScalar(0);
        _ringObj.updateMatrix();
        ring.setMatrixAt(instanceIdx, _ringObj.matrix);
      }
    }
  }
}
```

### 3f. Update ring needsUpdate block

The existing block at lines ~212-215 is fine as-is:

```typescript
if (ring) {
  ring.instanceMatrix.needsUpdate = true;
  if (ring.instanceColor) ring.instanceColor.needsUpdate = true;
}
```

No change needed.

---

## Step 4: TypeScript Type

**File: `ui/src/store/types.ts`**

After the `ScheduledTaskView` interface (line ~421), add:

```typescript
// Service status (AD-436)

export interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'degraded';
}
```

This type is used in `BridgeSystem.tsx`. It can also be imported from the component's local definition — both are acceptable. Adding it to `types.ts` is cleaner for future use by other components.

---

## Step 5: Tests

### 5a. Backend tests in `tests/test_api_system.py` (NEW FILE)

```python
"""Tests for Bridge System API endpoints (AD-436)."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_runtime():
    """Minimal mock runtime for system endpoints."""
    runtime = MagicMock()
    runtime._started = True
    runtime.registry.count = 0
    runtime.registry.all.return_value = []

    # Services that exist
    runtime.ward_room = MagicMock()
    runtime.episodic_memory = MagicMock()
    runtime.trust_network = MagicMock()
    runtime._knowledge_store = MagicMock()
    runtime.cognitive_journal = MagicMock()
    runtime.codebase_index = MagicMock()
    runtime.skill_registry = MagicMock()
    runtime.skill_service = MagicMock()
    runtime.acm = MagicMock()
    runtime.hebbian_router = MagicMock()
    runtime.intent_bus = MagicMock()

    # Required for /api/health
    runtime.registry.all.return_value = []
    runtime.registry.count = 0

    return runtime


@pytest.fixture
def client(mock_runtime):
    """FastAPI test client."""
    from probos.api import create_app
    from starlette.testclient import TestClient
    app = create_app(mock_runtime)
    return TestClient(app)


class TestSystemServices:
    """GET /api/system/services"""

    def test_returns_all_services(self, client):
        """AD-436: Services endpoint lists all system services."""
        resp = client.get("/api/system/services")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        names = [s["name"] for s in data["services"]]
        assert "Ward Room" in names
        assert "Episodic Memory" in names
        assert "Trust Network" in names
        assert "ACM" in names

    def test_all_online_when_initialized(self, client):
        """AD-436: All services report online when initialized."""
        resp = client.get("/api/system/services")
        data = resp.json()
        for svc in data["services"]:
            assert svc["status"] == "online", f"{svc['name']} should be online"

    def test_offline_when_none(self, client, mock_runtime):
        """AD-436: Services report offline when set to None."""
        mock_runtime.ward_room = None
        mock_runtime.acm = None
        resp = client.get("/api/system/services")
        data = resp.json()
        statuses = {s["name"]: s["status"] for s in data["services"]}
        assert statuses["Ward Room"] == "offline"
        assert statuses["ACM"] == "offline"
        # Others should still be online
        assert statuses["Trust Network"] == "online"


class TestSystemShutdown:
    """POST /api/system/shutdown"""

    def test_shutdown_returns_status(self, client):
        """AD-436: Shutdown endpoint returns shutting_down status."""
        resp = client.post(
            "/api/system/shutdown",
            json={"reason": "Testing AD-436"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "shutting_down"
        assert data["reason"] == "Testing AD-436"

    def test_shutdown_no_reason(self, client):
        """AD-436: Shutdown works without a reason."""
        resp = client.post("/api/system/shutdown", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "shutting_down"
        assert data["reason"] == ""
```

### 5b. Frontend tests

Add vitest tests in `ui/src/components/bridge/__tests__/BridgeSystem.test.tsx` if the project has existing vitest component tests. If not, skip — the backend tests and visual verification are sufficient.

---

## Files Modified

| File | Change |
|------|--------|
| `src/probos/api.py` | Add `ShutdownRequest` model, `GET /api/system/services`, `POST /api/system/shutdown` |
| `ui/src/components/bridge/BridgeSystem.tsx` | **NEW** — ServiceStatusList, ShutdownControl, ThreadManagement |
| `ui/src/components/BridgePanel.tsx` | Import BridgeSystem, add System section |
| `ui/src/canvas/agents.tsx` | Replace torus ring with orbital electrons (geometry, buffer, animation) |
| `ui/src/store/types.ts` | Add `ServiceStatus` interface |
| `tests/test_api_system.py` | **NEW** — 5 backend tests for system endpoints |

## Verification

1. `uv run pytest tests/test_api_system.py -v` — all 5 pass
2. `uv run pytest` — full regression green
3. `cd ui && npx vitest run` — vitest green
4. Visual: `uv run probos serve --interactive` → HXI → Bridge panel → "System" section shows services, shutdown, threads
5. Visual: Agents with notifications show orbiting electron dots on tilted orbital planes, not flat rings
