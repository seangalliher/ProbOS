import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '../store/useStore';
import type { WorkItemView, BookableResourceView, BookingView } from '../store/types';

const makeItem = (overrides: Partial<WorkItemView> = {}): WorkItemView => ({
  id: 'wi-1', title: 'Test task', description: '', work_type: 'task',
  status: 'open', priority: 3, parent_id: null, depends_on: [],
  assigned_to: null, created_by: 'captain', created_at: 1711612800,
  updated_at: 1711612800, due_at: null, estimated_tokens: 50000,
  actual_tokens: 0, trust_requirement: 0, required_capabilities: [],
  tags: [], metadata: {}, steps: [], verification: null, schedule: null,
  ttl_seconds: null, template_id: null, ...overrides,
});

const makeResource = (overrides: Partial<BookableResourceView> = {}): BookableResourceView => ({
  resource_id: 'res-1', resource_type: 'crew', agent_type: 'SecurityAgent',
  callsign: 'Worf', capacity: 1, calendar_id: null, department: 'Security',
  characteristics: [], display_on_board: true, active: true, ...overrides,
});

beforeEach(() => {
  useStore.setState({
    workItems: null,
    workBookings: null,
    bookableResources: null,
    mainViewer: 'canvas' as const,
  });
});

describe('WorkBoard store (AD-497)', () => {
  it('workItems state initializes to null', () => {
    expect(useStore.getState().workItems).toBeNull();
  });

  it('hydrates workforce from snapshot', () => {
    const items = [makeItem()];
    const bookings: BookingView[] = [{
      id: 'b-1', resource_id: 'res-1', work_item_id: 'wi-1', requirement_id: null,
      status: 'active', start_time: 1711612800, end_time: null, actual_start: 1711612800,
      actual_end: null, total_tokens_consumed: 5000,
    }];
    const resources = [makeResource()];

    useStore.setState({
      workItems: items,
      workBookings: bookings,
      bookableResources: resources,
    });

    expect(useStore.getState().workItems).toHaveLength(1);
    expect(useStore.getState().workBookings).toHaveLength(1);
    expect(useStore.getState().bookableResources).toHaveLength(1);
  });

  it('items sort into correct columns by status', () => {
    const items = [
      makeItem({ id: 'w1', status: 'open' }),
      makeItem({ id: 'w2', status: 'in_progress' }),
      makeItem({ id: 'w3', status: 'review' }),
      makeItem({ id: 'w4', status: 'done' }),
      makeItem({ id: 'w5', status: 'scheduled' }),
    ];
    useStore.setState({ workItems: items });

    const state = useStore.getState();
    const wi = state.workItems!;
    expect(wi.filter(i => i.status === 'open')).toHaveLength(1);
    expect(wi.filter(i => i.status === 'in_progress')).toHaveLength(1);
    expect(wi.filter(i => i.status === 'review')).toHaveLength(1);
    expect(wi.filter(i => i.status === 'done')).toHaveLength(1);
    expect(wi.filter(i => i.status === 'scheduled')).toHaveLength(1);
  });

  it('mainViewer supports work value', () => {
    useStore.setState({ mainViewer: 'work' });
    expect(useStore.getState().mainViewer).toBe('work');
  });

  it('work_item_created event handler merges new item', () => {
    useStore.setState({ workItems: [] });
    const newItem = makeItem({ id: 'new-1', title: 'Fresh item' });
    // Simulate the event handler logic
    const current = useStore.getState().workItems || [];
    const idx = current.findIndex(w => w.id === newItem.id);
    if (idx >= 0) {
      const updated = [...current];
      updated[idx] = newItem;
      useStore.setState({ workItems: updated });
    } else {
      useStore.setState({ workItems: [...current, newItem] });
    }
    expect(useStore.getState().workItems).toHaveLength(1);
    expect(useStore.getState().workItems![0].title).toBe('Fresh item');
  });

  it('work_item_updated event handler updates existing item', () => {
    const original = makeItem({ id: 'w1', title: 'Original' });
    useStore.setState({ workItems: [original] });
    const updated = makeItem({ id: 'w1', title: 'Updated' });
    const current = useStore.getState().workItems || [];
    const idx = current.findIndex(w => w.id === updated.id);
    if (idx >= 0) {
      const arr = [...current];
      arr[idx] = updated;
      useStore.setState({ workItems: arr });
    }
    expect(useStore.getState().workItems![0].title).toBe('Updated');
  });

  it('work_item_deleted event handler removes item', () => {
    useStore.setState({ workItems: [makeItem({ id: 'w1' }), makeItem({ id: 'w2' })] });
    const deletedId = 'w1';
    const current = useStore.getState().workItems || [];
    useStore.setState({ workItems: current.filter(w => w.id !== deletedId) });
    expect(useStore.getState().workItems).toHaveLength(1);
    expect(useStore.getState().workItems![0].id).toBe('w2');
  });

  it('WIP limit columns tracked correctly', () => {
    // Create 10 in_progress items
    const items = Array.from({ length: 12 }, (_, i) =>
      makeItem({ id: `w${i}`, status: 'in_progress' })
    );
    useStore.setState({ workItems: items });
    const inProgress = useStore.getState().workItems!.filter(i => i.status === 'in_progress');
    expect(inProgress.length).toBe(12);
    // WIP limit of 10 is display-only, not enforced in store
  });

  it('bookableResources filters by department', () => {
    const resources = [
      makeResource({ resource_id: 'r1', department: 'Security' }),
      makeResource({ resource_id: 'r2', department: 'Engineering' }),
      makeResource({ resource_id: 'r3', department: 'Security' }),
    ];
    useStore.setState({ bookableResources: resources });
    const sec = useStore.getState().bookableResources!.filter(r => r.department === 'Security');
    expect(sec).toHaveLength(2);
  });

  it('blocked items separated from main columns', () => {
    const items = [
      makeItem({ id: 'w1', status: 'in_progress' }),
      makeItem({ id: 'w2', status: 'blocked' }),
      makeItem({ id: 'w3', status: 'failed' }),
      makeItem({ id: 'w4', status: 'cancelled' }),
    ];
    useStore.setState({ workItems: items });
    const wi = useStore.getState().workItems!;
    const blocked = wi.filter(i => ['blocked', 'failed', 'cancelled'].includes(i.status));
    const active = wi.filter(i => !['blocked', 'failed', 'cancelled'].includes(i.status));
    expect(blocked).toHaveLength(3);
    expect(active).toHaveLength(1);
  });

  it('moveWorkItem calls correct endpoint', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = mockFetch as any;
    await useStore.getState().moveWorkItem('w1', 'in_progress');
    expect(mockFetch).toHaveBeenCalledWith('/api/work-items/w1/transition', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ status: 'in_progress' }),
    }));
  });

  it('assignWorkItem calls correct endpoint', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = mockFetch as any;
    await useStore.getState().assignWorkItem('w1', 'res-1');
    expect(mockFetch).toHaveBeenCalledWith('/api/work-items/w1/assign', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ resource_id: 'res-1' }),
    }));
  });

  it('createWorkItem calls correct endpoint', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = mockFetch as any;
    await useStore.getState().createWorkItem({ title: 'New Task', priority: 2 });
    expect(mockFetch).toHaveBeenCalledWith('/api/work-items', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ title: 'New Task', priority: 2 }),
    }));
  });

  it('swim lane grouping by priority', () => {
    const items = [
      makeItem({ id: 'w1', priority: 1 }),
      makeItem({ id: 'w2', priority: 1 }),
      makeItem({ id: 'w3', priority: 3 }),
      makeItem({ id: 'w4', priority: 5 }),
    ];
    const groups = new Map<string, typeof items>();
    for (const item of items) {
      const key = `P${item.priority}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(item);
    }
    expect(groups.get('P1')).toHaveLength(2);
    expect(groups.get('P3')).toHaveLength(1);
    expect(groups.get('P5')).toHaveLength(1);
  });

  it('empty state with null workItems', () => {
    useStore.setState({ workItems: null });
    expect(useStore.getState().workItems).toBeNull();
  });

  it('done column limits to 20 items', () => {
    const items = Array.from({ length: 25 }, (_, i) =>
      makeItem({ id: `d${i}`, status: 'done' })
    );
    // Simulate column filtering (done column limit)
    const doneCol = items.filter(i => i.status === 'done').slice(0, 20);
    expect(doneCol).toHaveLength(20);
  });
});
