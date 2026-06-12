# AD-834 — Natural-Language Task Creation + Dispatch (HXI Work Tab)

**Status:** Ready
**Dependencies:** AD-496/497/498 (WorkItem model + Work Tab), AD-581a (WorkItemRouter dispatch), AD-654c (Dispatcher)
**Estimated tests:** 3 vitest (form render + create payload + dispatch toggle)

## Problem

Creating a task for an agent in the HXI is a poor experience. The "Create Task" form in
the Work tab collects only a **title** and a **priority** — there is no way to describe in
natural language what the agent should actually do, and a manually-created task **never
executes**.

Grounded specifics:

1. The form ([`ProfileWorkTab.tsx:222-240`](../ui/src/components/profile/ProfileWorkTab.tsx)) has a single-line
   title `<input>` + a P1–P5 `<select>`. No description / instructions field.
2. `handleCreate()` ([`ProfileWorkTab.tsx:78-86`](../ui/src/components/profile/ProfileWorkTab.tsx)) posts only
   `{ title, priority, work_type: 'task', assigned_to }`.
3. The backend already accepts more: `POST /api/work-items`
   ([`routers/workforce.py:103-114`](../src/probos/routers/workforce.py)) does
   `create_work_item(**body)`, and `WorkItem` already has `description`, `tags`, and
   `metadata` fields.
4. The execution engine is **already wired end-to-end in OSS**: `WorkItemRouter`
   ([`mesh/work_item_router.py:104`](../src/probos/mesh/work_item_router.py)) already forwards
   `"description": wi.get("description", "")` in the dispatched task payload to the
   assigned CognitiveAgent (perceive → decide → act). The agent can already drive the
   browser tool ([`tools/browser/tool.py`](../src/probos/tools/browser/tool.py)).

The **only** reason a manually-created task does nothing is the dispatch gate:
`is_dispatchable()` ([`work_item_router.py:62-69`](../src/probos/mesh/work_item_router.py)) returns
True only if the item carries a configured `dispatchable` tag OR
`metadata["dispatchable"] == True`. The UI never sets either, so the task is inert.

**Net:** the engine exists; the UI just doesn't expose the description field or the
dispatch flag. This is a near-pure UI fix that activates capability already present.

## Solution

Extend the Create Task form (and only the form + its store action) to:

1. Add a **natural-language instructions** `<textarea>` → sent as `description`.
2. Add a **"Dispatch to agent now"** toggle (default ON). When ON, include
   `metadata: { dispatchable: true }` so `WorkItemRouter` routes the task to the assigned
   agent for execution. When OFF, the task is created as a draft (current inert behavior).
3. Forward `description` + `metadata` through the existing `createWorkItem` store action.

No backend changes. No new execution machinery. No new config.

## Implementation

### Section 1 — Store action: forward `metadata`

File: `ui/src/store/useStore.ts`

```typescript
===MODIFY: ui/src/store/useStore.ts===
===SEARCH===
  createWorkItem: (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string }) => Promise<void>;
===REPLACE===
  createWorkItem: (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string; metadata?: Record<string, unknown> }) => Promise<void>;
===END REPLACE===
```

```typescript
===MODIFY: ui/src/store/useStore.ts===
===SEARCH===
  createWorkItem: async (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string }) => {
    try {
      const resp = await fetch('/api/work-items', {
===REPLACE===
  createWorkItem: async (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string; metadata?: Record<string, unknown> }) => {
    try {
      const resp = await fetch('/api/work-items', {
===END REPLACE===
```

### Section 2 — Form state + handleCreate

File: `ui/src/components/profile/ProfileWorkTab.tsx`

```tsx
===MODIFY: ui/src/components/profile/ProfileWorkTab.tsx===
===SEARCH===
  const [showCreate, setShowCreate] = useState(false);
  const [createTitle, setCreateTitle] = useState('');
  const [createPriority, setCreatePriority] = useState(3);
===REPLACE===
  const [showCreate, setShowCreate] = useState(false);
  const [createTitle, setCreateTitle] = useState('');
  const [createPriority, setCreatePriority] = useState(3);
  const [createInstructions, setCreateInstructions] = useState('');
  const [dispatchNow, setDispatchNow] = useState(true);
===END REPLACE===
```

```tsx
===MODIFY: ui/src/components/profile/ProfileWorkTab.tsx===
===SEARCH===
  const handleCreate = useCallback(async () => {
    if (!createTitle.trim()) return;
    await createWorkItem({ title: createTitle.trim(), priority: createPriority, work_type: 'task', assigned_to: agentUuid });
    setCreateTitle('');
    setCreatePriority(3);
    setShowCreate(false);
  }, [createTitle, createPriority, agentUuid, createWorkItem]);
===REPLACE===
  const handleCreate = useCallback(async () => {
    if (!createTitle.trim()) return;
    await createWorkItem({
      title: createTitle.trim(),
      priority: createPriority,
      work_type: 'task',
      assigned_to: agentUuid,
      description: createInstructions.trim() || undefined,
      // AD-834: dispatch flag activates WorkItemRouter -> assigned agent.
      metadata: dispatchNow ? { dispatchable: true } : undefined,
    });
    setCreateTitle('');
    setCreatePriority(3);
    setCreateInstructions('');
    setDispatchNow(true);
    setShowCreate(false);
  }, [createTitle, createPriority, createInstructions, dispatchNow, agentUuid, createWorkItem]);
===END REPLACE===
```

### Section 3 — Form UI: instructions textarea + dispatch toggle

File: `ui/src/components/profile/ProfileWorkTab.tsx`

Insert the textarea between the title input and the priority/buttons row, and add the
dispatch toggle to the controls row.

```tsx
===MODIFY: ui/src/components/profile/ProfileWorkTab.tsx===
===SEARCH===
            <input
              value={createTitle} onChange={e => setCreateTitle(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              placeholder="Task title..."
              autoFocus
              style={{
                width: '100%', padding: '3px 6px', fontSize: 11, borderRadius: 3,
                background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)',
                color: '#c8d0e0', outline: 'none', marginBottom: 4, boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <select value={createPriority} onChange={e => setCreatePriority(Number(e.target.value))}
                style={{ fontSize: 10, padding: '2px 4px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#aaa', borderRadius: 3 }}>
                {[1,2,3,4,5].map(p => <option key={p} value={p}>P{p}</option>)}
              </select>
              <button onClick={handleCreate} style={{ ...actionBtnStyle, color: '#50b0a0', borderColor: 'rgba(80,176,160,0.3)' }}>Create</button>
              <button onClick={() => setShowCreate(false)} style={actionBtnStyle}>Cancel</button>
            </div>
===REPLACE===
            <input
              value={createTitle} onChange={e => setCreateTitle(e.target.value)}
              placeholder="Task title..."
              autoFocus
              style={{
                width: '100%', padding: '3px 6px', fontSize: 11, borderRadius: 3,
                background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)',
                color: '#c8d0e0', outline: 'none', marginBottom: 4, boxSizing: 'border-box',
              }}
            />
            <textarea
              value={createInstructions} onChange={e => setCreateInstructions(e.target.value)}
              placeholder="Describe what the agent should do (natural language)..."
              rows={3}
              style={{
                width: '100%', padding: '4px 6px', fontSize: 11, borderRadius: 3,
                background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)',
                color: '#c8d0e0', outline: 'none', marginBottom: 4, boxSizing: 'border-box',
                resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.4,
              }}
            />
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <select value={createPriority} onChange={e => setCreatePriority(Number(e.target.value))}
                style={{ fontSize: 10, padding: '2px 4px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#aaa', borderRadius: 3 }}>
                {[1,2,3,4,5].map(p => <option key={p} value={p}>P{p}</option>)}
              </select>
              <label style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 10, color: '#8888a0', cursor: 'pointer' }}>
                <input type="checkbox" checked={dispatchNow} onChange={e => setDispatchNow(e.target.checked)}
                  style={{ cursor: 'pointer' }} />
                Dispatch to agent now
              </label>
              <button onClick={handleCreate} style={{ ...actionBtnStyle, color: '#50b0a0', borderColor: 'rgba(80,176,160,0.3)' }}>Create</button>
              <button onClick={() => setShowCreate(false)} style={actionBtnStyle}>Cancel</button>
            </div>
===END REPLACE===
```

> Note: the Enter-to-submit handler is removed from the title input because a
> multi-line instructions textarea is now the primary input; submit is via the Create
> button. This is intentional.

## Tests

New file: `ui/src/components/profile/ProfileWorkTab.create.test.tsx` (vitest + Testing Library)

1. **Renders instructions textarea + dispatch toggle** — open the create form, assert the
   textarea (placeholder "Describe what the agent should do…") and the "Dispatch to agent
   now" checkbox are present.
2. **Create payload includes description + dispatchable metadata** — fill title +
   instructions, leave toggle ON, click Create; assert the `createWorkItem` store action
   was called with `description` set and `metadata: { dispatchable: true }`.
3. **Dispatch toggle OFF omits dispatchable** — uncheck the toggle, click Create; assert
   `metadata` is `undefined` (draft, not dispatched).

Run: `cd ui && npx vitest run ProfileWorkTab.create`

## What This Does NOT Change

- No backend changes — `create_work_item(**body)` already accepts `description` + `metadata`.
- No change to `WorkItemRouter`, `DepartmentDispatcher`, or the Dispatcher — they already
  forward `description` and gate on `metadata.dispatchable`.
- No change to the "From Template" flow.
- No change to the duty-schedule path.
- Does NOT build the commercial immersive cockpit (3D glass overlay, embedded browser
  panel, BPMN editor) — those remain AD-C-022 (commercial) scope.

## Tracking

- `PROGRESS.md` — add AD-834 CLOSED entry (one line).
- `decisions-era-5-unification.md` — append AD-834: NL task creation + dispatch toggle;
  activates the already-wired WorkItem dispatch engine from the HXI.

## Acceptance Criteria

1. The Create Task form shows a natural-language instructions textarea and a "Dispatch to
   agent now" toggle.
2. Creating with the toggle ON produces a task that `WorkItemRouter.is_dispatchable()`
   accepts (carries `metadata.dispatchable == true`) and is routed to the assigned agent.
3. `cd ui && npx vitest run ProfileWorkTab.create` passes (3 tests).
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-31)

```
ui/src/components/profile/ProfileWorkTab.tsx:78-86   handleCreate -> {title,priority,work_type,assigned_to}
ui/src/components/profile/ProfileWorkTab.tsx:222-240 form: title <input> + priority <select> only
ui/src/store/useStore.ts:1306                        createWorkItem posts body as-is to /api/work-items
src/probos/routers/workforce.py:103-114              create_work_item(**body)  (accepts description + metadata)
src/probos/mesh/work_item_router.py:62-69            is_dispatchable: tag OR metadata["dispatchable"]
src/probos/mesh/work_item_router.py:104              payload forwards "description" to assigned agent
src/probos/tools/browser/tool.py                     browser tool already OSS (10-action vocabulary)
```
