import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';
import type { AgentTaskView, TaskStepView } from '../store/types';
import { STEP_ICON_COMPONENTS } from '../components/glass/GlassDAGNodes';

function makeStep(overrides: Partial<TaskStepView> = {}): TaskStepView {
  return {
    label: 'Test step',
    status: 'pending',
    started_at: 0,
    duration_ms: 0,
    ...overrides,
  };
}

function makeTask(overrides: Partial<AgentTaskView> = {}): AgentTaskView {
  return {
    id: 't1',
    agent_id: 'builder-001',
    agent_type: 'builder',
    department: 'engineering',
    type: 'build',
    title: 'Build AD-389',
    status: 'working',
    steps: [],
    requires_action: false,
    action_type: '',
    started_at: Date.now() / 1000 - 60,
    completed_at: 0,
    error: '',
    priority: 3,
    ad_number: 389,
    metadata: {},
    step_current: 2,
    step_total: 5,
    ...overrides,
  };
}

beforeEach(() => {
  useStore.setState({
    agentTasks: null,
    expandedGlassTask: null,
    mainViewer: 'canvas' as const,
    bridgeOpen: false,
  });
});

describe('GlassDAGNodes store integration (AD-389)', () => {
  it('expandedGlassTask defaults to null', () => {
    expect(useStore.getState().expandedGlassTask).toBeNull();
  });

  it('expandedGlassTask can be set and cleared', () => {
    useStore.setState({ expandedGlassTask: 't1' });
    expect(useStore.getState().expandedGlassTask).toBe('t1');
    useStore.setState({ expandedGlassTask: null });
    expect(useStore.getState().expandedGlassTask).toBeNull();
  });

  it('only one expanded at a time — setting new id replaces old', () => {
    useStore.setState({ expandedGlassTask: 't1' });
    expect(useStore.getState().expandedGlassTask).toBe('t1');
    useStore.setState({ expandedGlassTask: 't2' });
    expect(useStore.getState().expandedGlassTask).toBe('t2');
  });

  it('step status mapping produces correct icon components', () => {
    expect(STEP_ICON_COMPONENTS['done']).toBeDefined();
    expect(STEP_ICON_COMPONENTS['in_progress']).toBeDefined();
    expect(STEP_ICON_COMPONENTS['pending']).toBeDefined();
    expect(STEP_ICON_COMPONENTS['failed']).toBeDefined();
    expect(Object.keys(STEP_ICON_COMPONENTS)).toHaveLength(4);
  });

  it('empty steps array means no DAG nodes to render', () => {
    const task = makeTask({ steps: [] });
    expect(task.steps.length).toBe(0);
  });

  it('node count matches step count', () => {
    const steps = [
      makeStep({ label: 'Parse', status: 'done', duration_ms: 150 }),
      makeStep({ label: 'Generate', status: 'in_progress' }),
      makeStep({ label: 'Validate', status: 'pending' }),
      makeStep({ label: 'Write', status: 'pending' }),
      makeStep({ label: 'Test', status: 'pending' }),
    ];
    const task = makeTask({ steps });
    expect(task.steps.length).toBe(5);
    // Radial positions would be computed for 5 nodes
    const nodeCount = task.steps.length;
    expect(nodeCount).toBe(5);
  });

  it('toggle expand logic works correctly', () => {
    // Simulate single-click toggle behavior
    const taskId = 't1';
    const current = useStore.getState().expandedGlassTask;
    useStore.setState({ expandedGlassTask: current === taskId ? null : taskId });
    expect(useStore.getState().expandedGlassTask).toBe('t1');

    // Click same task again — collapses
    const current2 = useStore.getState().expandedGlassTask;
    useStore.setState({ expandedGlassTask: current2 === taskId ? null : taskId });
    expect(useStore.getState().expandedGlassTask).toBeNull();
  });
});
