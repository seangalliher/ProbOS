import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '../store/useStore';
import type { WorkItemView, BookableResourceView, BookingView, Agent } from '../store/types';

const makeItem = (overrides: Partial<WorkItemView> = {}): WorkItemView => ({
  id: 'wi-1', title: 'Test task', description: '', work_type: 'task',
  status: 'open', priority: 3, parent_id: null, depends_on: [],
  assigned_to: 'res-1', created_by: 'captain', created_at: 1711612800,
  updated_at: 1711612800, due_at: null, estimated_tokens: 50000,
  actual_tokens: 0, trust_requirement: 0, required_capabilities: [],
  tags: [], metadata: {}, steps: [], verification: null, schedule: null,
  ttl_seconds: null, template_id: null, ...overrides,
});

beforeEach(() => {
  useStore.setState({
    workItems: null,
    workBookings: null,
    bookableResources: null,
    scheduledTasks: [],
    agents: new Map(),
  });
});

describe('ProfileWorkTab store (AD-497)', () => {
  it('filters work items by assigned agent', () => {
    const items = [
      makeItem({ id: 'w1', assigned_to: 'res-1', status: 'in_progress' }),
      makeItem({ id: 'w2', assigned_to: 'res-2', status: 'open' }),
      makeItem({ id: 'w3', assigned_to: 'res-1', status: 'review' }),
    ];
    useStore.setState({ workItems: items });
    const agentItems = useStore.getState().workItems!.filter(w => w.assigned_to === 'res-1');
    expect(agentItems).toHaveLength(2);
  });

  it('separates active and blocked items', () => {
    const items = [
      makeItem({ id: 'w1', assigned_to: 'res-1', status: 'in_progress' }),
      makeItem({ id: 'w2', assigned_to: 'res-1', status: 'blocked' }),
      makeItem({ id: 'w3', assigned_to: 'res-1', status: 'failed' }),
    ];
    useStore.setState({ workItems: items });
    const mine = useStore.getState().workItems!.filter(w => w.assigned_to === 'res-1');
    const active = mine.filter(w => ['open', 'scheduled', 'in_progress', 'review'].includes(w.status));
    const blocked = mine.filter(w => ['failed', 'blocked'].includes(w.status));
    expect(active).toHaveLength(1);
    expect(blocked).toHaveLength(2);
  });

  it('matches booking to work item for token display', () => {
    const booking: BookingView = {
      id: 'b-1', resource_id: 'res-1', work_item_id: 'wi-1',
      requirement_id: null, status: 'active', start_time: 1711612800,
      end_time: null, actual_start: 1711612800, actual_end: null,
      total_tokens_consumed: 12500,
    };
    useStore.setState({ workBookings: [booking] });
    const bookings = useStore.getState().workBookings!.filter(
      b => b.resource_id === 'res-1' && b.work_item_id === 'wi-1'
    );
    expect(bookings).toHaveLength(1);
    expect(bookings[0].total_tokens_consumed).toBe(12500);
  });

  it('scheduled tasks included for duty schedule', () => {
    useStore.setState({
      scheduledTasks: [
        { name: 'Scout Report', status: 'pending', next_run_at: Date.now() / 1000 + 3600 } as any,
      ],
    });
    expect(useStore.getState().scheduledTasks).toHaveLength(1);
  });

  it('createWorkItem calls API with assigned_to', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = mockFetch as any;
    await useStore.getState().createWorkItem({
      title: 'New task', priority: 2, work_type: 'task', assigned_to: 'res-1',
    });
    expect(mockFetch).toHaveBeenCalledWith('/api/work-items', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ title: 'New task', priority: 2, work_type: 'task', assigned_to: 'res-1' }),
    }));
  });

  it('empty state when no items assigned', () => {
    useStore.setState({ workItems: [] });
    const mine = useStore.getState().workItems!.filter(w => w.assigned_to === 'res-1');
    expect(mine).toHaveLength(0);
  });

  it('bookableResources provides agent list for reassign', () => {
    const resources: BookableResourceView[] = [
      { resource_id: 'res-1', resource_type: 'crew', agent_type: 'SecurityAgent', callsign: 'Worf', capacity: 1, calendar_id: null, department: 'Security', characteristics: [], display_on_board: true, active: true },
      { resource_id: 'res-2', resource_type: 'crew', agent_type: 'EngineeringAgent', callsign: 'LaForge', capacity: 1, calendar_id: null, department: 'Engineering', characteristics: [], display_on_board: true, active: true },
    ];
    useStore.setState({ bookableResources: resources });
    const available = useStore.getState().bookableResources!.filter(r => r.active && r.display_on_board);
    expect(available).toHaveLength(2);
  });
});
