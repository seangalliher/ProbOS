import { describe, it, expect } from 'vitest';
import { deriveBridgeState } from '../components/glass/ContextRibbon';
import { EDGE_GLOW } from '../components/GlassLayer';
import type { AgentTaskView, NotificationView } from '../store/types';

function makeTask(overrides: Partial<AgentTaskView> = {}): AgentTaskView {
  return {
    id: 't1',
    agent_id: 'builder-001',
    agent_type: 'builder',
    department: 'engineering',
    type: 'build',
    title: 'Build AD-390',
    status: 'working',
    steps: [],
    requires_action: false,
    action_type: '',
    started_at: Date.now() / 1000 - 60,
    completed_at: 0,
    error: '',
    priority: 3,
    ad_number: 390,
    metadata: {},
    step_current: 2,
    step_total: 5,
    ...overrides,
  };
}

function makeNotif(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    id: 'n1',
    agent_id: 'monitor-001',
    agent_type: 'monitor',
    department: 'medical',
    notification_type: 'info',
    title: 'Test notification',
    detail: '',
    action_url: '',
    created_at: Date.now() / 1000,
    acknowledged: false,
    ...overrides,
  };
}

describe('deriveBridgeState (AD-390)', () => {
  it('returns idle when no tasks', () => {
    expect(deriveBridgeState(null, null)).toBe('idle');
    expect(deriveBridgeState([], null)).toBe('idle');
    expect(deriveBridgeState([], [])).toBe('idle');
  });

  it('returns idle when all tasks are done/failed', () => {
    const tasks = [
      makeTask({ id: 't1', status: 'done' }),
      makeTask({ id: 't2', status: 'failed' }),
    ];
    expect(deriveBridgeState(tasks, null)).toBe('idle');
  });

  it('returns autonomous when active tasks exist but none need attention', () => {
    const tasks = [
      makeTask({ id: 't1', status: 'working', requires_action: false }),
      makeTask({ id: 't2', status: 'queued', requires_action: false }),
    ];
    expect(deriveBridgeState(tasks, null)).toBe('autonomous');
  });

  it('returns attention when any task has requires_action', () => {
    const tasks = [
      makeTask({ id: 't1', status: 'working', requires_action: false }),
      makeTask({ id: 't2', status: 'review', requires_action: true }),
    ];
    expect(deriveBridgeState(tasks, null)).toBe('attention');
  });

  it('returns attention when notification has action_required', () => {
    const tasks = [
      makeTask({ id: 't1', status: 'working', requires_action: false }),
    ];
    const notifs = [
      makeNotif({ notification_type: 'action_required', acknowledged: false }),
    ];
    expect(deriveBridgeState(tasks, notifs)).toBe('attention');
  });

  it('returns autonomous when action_required notification is acknowledged', () => {
    const tasks = [
      makeTask({ id: 't1', status: 'working', requires_action: false }),
    ];
    const notifs = [
      makeNotif({ notification_type: 'action_required', acknowledged: true }),
    ];
    expect(deriveBridgeState(tasks, notifs)).toBe('autonomous');
  });
});

describe('edge glow mapping (AD-390)', () => {
  it('maps idle to cyan glow', () => {
    expect(EDGE_GLOW['idle']).toContain('56, 200, 192');
  });

  it('maps autonomous to golden glow', () => {
    expect(EDGE_GLOW['autonomous']).toContain('212, 160, 41');
  });

  it('maps attention to amber glow', () => {
    expect(EDGE_GLOW['attention']).toContain('240, 174, 64');
  });
});

describe('celebration detection logic (AD-390)', () => {
  it('detects status transition from working to done', () => {
    const prevStatuses = new Map<string, string>();
    prevStatuses.set('t1', 'working');

    const tasks = [makeTask({ id: 't1', status: 'done' })];
    const celebrations = new Set<string>();

    for (const task of tasks) {
      const prev = prevStatuses.get(task.id);
      if (prev && prev !== 'done' && prev !== 'failed' && task.status === 'done') {
        celebrations.add(task.id);
      }
    }

    expect(celebrations.has('t1')).toBe(true);
  });

  it('does not celebrate if previous status was already done', () => {
    const prevStatuses = new Map<string, string>();
    prevStatuses.set('t1', 'done');

    const tasks = [makeTask({ id: 't1', status: 'done' })];
    const celebrations = new Set<string>();

    for (const task of tasks) {
      const prev = prevStatuses.get(task.id);
      if (prev && prev !== 'done' && prev !== 'failed' && task.status === 'done') {
        celebrations.add(task.id);
      }
    }

    expect(celebrations.has('t1')).toBe(false);
  });
});
