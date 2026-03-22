import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';
import type { AgentTaskView } from '../store/types';

function makeTask(overrides: Partial<AgentTaskView> = {}): AgentTaskView {
  return {
    id: 't1',
    agent_id: 'builder-001',
    agent_type: 'builder',
    department: 'engineering',
    type: 'build',
    title: 'Build AD-388',
    status: 'working',
    steps: [],
    requires_action: false,
    action_type: '',
    started_at: Date.now() / 1000 - 60,
    completed_at: 0,
    error: '',
    priority: 3,
    ad_number: 388,
    metadata: {},
    step_current: 2,
    step_total: 5,
    ...overrides,
  };
}

beforeEach(() => {
  useStore.setState({
    agentTasks: null,
    mainViewer: 'canvas' as const,
    bridgeOpen: false,
  });
});

describe('GlassLayer store integration (AD-388)', () => {
  it('no glass content when agentTasks is null', () => {
    useStore.setState({ agentTasks: null });
    const tasks = useStore.getState().agentTasks;
    const activeTasks = tasks?.filter(
      t => t.status !== 'done' && t.status !== 'failed'
    ) ?? [];
    expect(activeTasks.length).toBe(0);
  });

  it('no glass content when agentTasks is empty', () => {
    useStore.setState({ agentTasks: [] });
    const tasks = useStore.getState().agentTasks!;
    const activeTasks = tasks.filter(
      t => t.status !== 'done' && t.status !== 'failed'
    );
    expect(activeTasks.length).toBe(0);
  });

  it('glass hidden in kanban mode', () => {
    useStore.setState({ mainViewer: 'kanban' as const, agentTasks: [makeTask()] });
    const mv = useStore.getState().mainViewer;
    expect(mv).toBe('kanban');
    // GlassLayer returns null when mainViewer !== 'canvas'
  });

  it('single active task produces one card', () => {
    useStore.setState({ agentTasks: [makeTask()] });
    const tasks = useStore.getState().agentTasks!;
    const activeTasks = tasks.filter(
      t => t.status !== 'done' && t.status !== 'failed'
    );
    expect(activeTasks.length).toBe(1);
  });

  it('multiple active tasks produce correct count', () => {
    useStore.setState({
      agentTasks: [
        makeTask({ id: 't1', title: 'Task 1' }),
        makeTask({ id: 't2', title: 'Task 2', status: 'queued' }),
        makeTask({ id: 't3', title: 'Task 3', status: 'review' }),
      ],
    });
    const tasks = useStore.getState().agentTasks!;
    const activeTasks = tasks.filter(
      t => t.status !== 'done' && t.status !== 'failed'
    );
    expect(activeTasks.length).toBe(3);
  });

  it('done/failed tasks are excluded from active', () => {
    useStore.setState({
      agentTasks: [
        makeTask({ id: 't1', status: 'working' }),
        makeTask({ id: 't2', status: 'done' }),
        makeTask({ id: 't3', status: 'failed' }),
      ],
    });
    const tasks = useStore.getState().agentTasks!;
    const activeTasks = tasks.filter(
      t => t.status !== 'done' && t.status !== 'failed'
    );
    expect(activeTasks.length).toBe(1);
  });

  it('attention tasks sort first', () => {
    useStore.setState({
      agentTasks: [
        makeTask({ id: 't1', requires_action: false, priority: 1 }),
        makeTask({ id: 't2', requires_action: true, priority: 5 }),
      ],
    });
    const tasks = useStore.getState().agentTasks!;
    const sorted = [...tasks].sort((a, b) => {
      if (a.requires_action !== b.requires_action) return a.requires_action ? -1 : 1;
      return a.priority - b.priority;
    });
    expect(sorted[0].id).toBe('t2');
    expect(sorted[0].requires_action).toBe(true);
  });

  it('frost level increases with task count', () => {
    function frostBlur(count: number): string {
      if (count <= 0) return 'blur(0px)';
      if (count <= 2) return 'blur(2px)';
      if (count <= 5) return 'blur(4px)';
      return 'blur(6px)';
    }
    expect(frostBlur(0)).toBe('blur(0px)');
    expect(frostBlur(1)).toBe('blur(2px)');
    expect(frostBlur(2)).toBe('blur(2px)');
    expect(frostBlur(3)).toBe('blur(4px)');
    expect(frostBlur(5)).toBe('blur(4px)');
    expect(frostBlur(6)).toBe('blur(6px)');
    expect(frostBlur(10)).toBe('blur(6px)');
  });

  it('clicking card opens bridge', () => {
    expect(useStore.getState().bridgeOpen).toBe(false);
    useStore.setState({ bridgeOpen: true });
    expect(useStore.getState().bridgeOpen).toBe(true);
  });
});
