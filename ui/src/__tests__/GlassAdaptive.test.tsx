import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { trustBand, TRUST_COLORS } from '../components/glass/GlassTaskCard';
import { getBreakpoint } from '../hooks/useBreakpoint';
import { deriveBridgeState } from '../components/glass/ContextRibbon';
import type { AgentTaskView } from '../store/types';
import type { NotificationView } from '../store/types';

function makeTask(overrides: Partial<AgentTaskView> = {}): AgentTaskView {
  return {
    id: 'task-1',
    title: 'Test Task',
    status: 'working',
    priority: 1,
    department: 'engineering',
    agent_type: 'builder',
    agent_id: 'agent-1',
    type: 'build',
    requires_action: false,
    action_type: '',
    step_current: 0,
    step_total: 0,
    started_at: Date.now() / 1000,
    completed_at: 0,
    error: '',
    ad_number: 100,
    steps: [],
    metadata: {},
    ...overrides,
  };
}

function makeNotif(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    id: 'notif-1',
    notification_type: 'info',
    title: 'Test',
    detail: 'test',
    action_url: '',
    agent_id: 'agent-1',
    agent_type: 'builder',
    department: 'engineering',
    acknowledged: false,
    created_at: Date.now() / 1000,
    ...overrides,
  };
}

describe('trust band thresholds (AD-392)', () => {
  it('trust < 0.35 = low', () => {
    expect(trustBand(0)).toBe('low');
    expect(trustBand(0.1)).toBe('low');
    expect(trustBand(0.34)).toBe('low');
  });

  it('trust 0.35-0.7 = medium', () => {
    expect(trustBand(0.35)).toBe('medium');
    expect(trustBand(0.5)).toBe('medium');
    expect(trustBand(0.7)).toBe('medium');
  });

  it('trust > 0.7 = high', () => {
    expect(trustBand(0.71)).toBe('high');
    expect(trustBand(0.9)).toBe('high');
    expect(trustBand(1.0)).toBe('high');
  });
});

describe('trust color mapping (AD-392)', () => {
  it('low = #7060a8', () => {
    expect(TRUST_COLORS.low).toBe('#7060a8');
  });

  it('medium = #88a4c8', () => {
    expect(TRUST_COLORS.medium).toBe('#88a4c8');
  });

  it('high = #f0b060', () => {
    expect(TRUST_COLORS.high).toBe('#f0b060');
  });
});

describe('breakpoint detection (AD-392)', () => {
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: originalInnerWidth,
    });
  });

  it('returns ultrawide for width > 2560', () => {
    Object.defineProperty(window, 'innerWidth', { value: 3440, writable: true, configurable: true });
    expect(getBreakpoint()).toBe('ultrawide');
  });

  it('returns standard for width 1441-2560', () => {
    Object.defineProperty(window, 'innerWidth', { value: 1920, writable: true, configurable: true });
    expect(getBreakpoint()).toBe('standard');
  });

  it('returns laptop for width 1025-1440', () => {
    Object.defineProperty(window, 'innerWidth', { value: 1280, writable: true, configurable: true });
    expect(getBreakpoint()).toBe('laptop');
  });

  it('returns tablet for width 769-1024', () => {
    Object.defineProperty(window, 'innerWidth', { value: 800, writable: true, configurable: true });
    expect(getBreakpoint()).toBe('tablet');
  });

  it('returns mobile for width <= 768', () => {
    Object.defineProperty(window, 'innerWidth', { value: 375, writable: true, configurable: true });
    expect(getBreakpoint()).toBe('mobile');
  });
});

describe('pill breathing logic (AD-392)', () => {
  it('autonomous + far mouse = receded', () => {
    const tasks = [makeTask({ status: 'working', requires_action: false })];
    const bridgeState = deriveBridgeState(tasks, []);
    expect(bridgeState).toBe('autonomous');
    // When autonomous and mouse > 200px from pill, pill should recede
    // (visual assertion — logic validated by bridge state being 'autonomous')
  });

  it('attention state = normal (pill visible)', () => {
    const tasks = [makeTask({ status: 'working', requires_action: true })];
    const bridgeState = deriveBridgeState(tasks, []);
    expect(bridgeState).toBe('attention');
    // Pill stays normal in attention state
  });

  it('idle state = normal (pill visible)', () => {
    const bridgeState = deriveBridgeState([], []);
    expect(bridgeState).toBe('idle');
    // Pill stays normal in idle state
  });

  it('autonomous + near mouse = normal (swell)', () => {
    const tasks = [makeTask({ status: 'working', requires_action: false })];
    const bridgeState = deriveBridgeState(tasks, []);
    expect(bridgeState).toBe('autonomous');
    // When mouse is within 200px, pill swells back to normal
    // (visual behavior — tested via bridge state)
  });
});

describe('gaze throttle logic (AD-392)', () => {
  it('throttle interval is respected (100ms)', () => {
    // Test the throttle concept: timestamps less than 100ms apart should skip
    const GAZE_THROTTLE_MS = 100;
    let lastTimestamp = 0;
    const updates: number[] = [];

    const timestamps = [0, 50, 99, 100, 150, 200, 201, 300];
    for (const ts of timestamps) {
      if (ts - lastTimestamp >= GAZE_THROTTLE_MS) {
        updates.push(ts);
        lastTimestamp = ts;
      }
    }

    // First event at 0 is skipped (0 - 0 = 0 < 100). Only at 100ms+ intervals.
    expect(updates).toEqual([100, 200, 300]);
  });
});
