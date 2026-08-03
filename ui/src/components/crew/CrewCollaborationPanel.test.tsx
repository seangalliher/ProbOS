import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import CrewCollaborationPanel from './CrewCollaborationPanel';
import { useStore } from '../../store/useStore';
import type {
  CrewSessionDetailProjection,
  CrewSessionState,
  LegacyCrewChildView,
  LegacyCrewWorkItemView,
} from '../../store/types';

const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

function projection(state: CrewSessionState): CrewSessionDetailProjection {
  const done = state === 'done';
  const blocked = state === 'blocked_needs_captain';
  return {
    task_id: 'p1',
    thread_id: 't1',
    goal: 'A very long CrewSession goal that must wrap inside its responsive room band',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'facilitator-1',
    owner_ids: ['facilitator-1', 'owner-with-a-long-identifier'],
    state,
    revision: 2,
    success_criteria: ['One long criterion that wraps without clipping'],
    expected_deliverable: 'A bounded verified readiness report',
    timestamps: {
      created_at: 1,
      transitioned_at: 3,
      started_at: state === 'executing' || state === 'verifying' || done ? 2 : null,
      first_result_at: state === 'verifying' || done ? 2.5 : null,
      verified_at: done ? 3 : null,
      completed_at: done || state === 'failed' ? 3 : null,
    },
    progress: {
      total: 4,
      done: 1,
      failed: 1,
      active: 2,
      active_child: state === 'failed' || done ? null : {
        id: 'child-1',
        title: 'Analyze an unusually long active child title',
        status: 'in_progress',
        owner_id: 'owner-2',
      },
    },
    last_result_summary: done ? 'The report passed verification.' : 'Draft analysis is available.',
    blocker: blocked ? {
      reason: 'Captain approval is required before the crew can continue.',
      since: 3,
      duration_seconds: 95,
      action: 'retry_start_work',
    } : null,
    result: done ? {
      artifact_id: 'artifact-1',
      content_hash: SHA_B,
      result_ref: SHA_A,
      evidence_refs: [SHA_A],
    } : null,
    verification: done ? {
      verifier_agent_id: 'verifier-1',
      confidence: 0.94,
      critique: 'All acceptance criteria are satisfied.',
      accepted_count: 2,
      total_count: 2,
      convergence_rounds: 1,
    } : null,
    duplicate_resume_count: 2,
  };
}

function legacyItem(
  id: string,
  title: string,
  parentId: string | null,
): LegacyCrewWorkItemView {
  return {
    id,
    title,
    description: 'Legacy crew work',
    work_type: 'task',
    status: 'in_progress',
    priority: 1,
    parent_id: parentId,
    project_id: null,
    depends_on: [],
    assigned_to: 'facilitator-1',
    created_by: 'captain',
    created_at: 1,
    updated_at: 2,
    due_at: null,
    estimated_tokens: null,
    actual_tokens: 0,
    trust_requirement: 0.5,
    required_capabilities: [],
    tags: [],
    metadata: {},
    steps: [],
    verification: {},
    schedule: {},
    ttl_seconds: null,
    template_id: null,
  };
}

function legacyChild(): LegacyCrewChildView {
  return {
    ...legacyItem('c1', 'Child', 'p1'),
    verdict: null,
    rounds: null,
  };
}

function stubFetch(body: unknown, status = 200): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
  vi.stubGlobal('fetch', mock);
  return mock;
}

afterEach(() => {
  cleanup();
  useStore.setState({
    crewSessionsByParent: new Map(),
    liveCrewOwnerParentId: null,
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('CrewCollaborationPanel', () => {
  it('claims only its mounted parent and releases ownership on unmount', async () => {
    stubFetch({ session: projection('executing') });
    const view = render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    await screen.findByTestId('crew-collaboration-panel');
    expect(useStore.getState().liveCrewOwnerParentId).toBe('p1');
    view.unmount();
    expect(useStore.getState().liveCrewOwnerParentId).toBeNull();
  });

  it('renders a same-revision live progress update from the immutable store map', async () => {
    const initial = projection('executing');
    stubFetch({ session: initial });
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    await screen.findByText('1/4');
    const progressed = {
      ...initial,
      progress: { ...initial.progress, done: 2, active: 1 },
      last_result_summary: 'Two children complete.',
    };
    act(() => useStore.getState().hydrateCrewSession('p1', progressed));
    expect(await screen.findByText('2/4')).toBeTruthy();
    expect(screen.getByText('Two children complete.')).toBeTruthy();
  });

  it.each([
    'discussing', 'executing', 'verifying', 'blocked_needs_captain', 'done', 'failed',
  ] as CrewSessionState[])('renders exact %s state semantics', async (state) => {
    stubFetch({ session: projection(state) });
    const { container } = render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    const panel = await screen.findByTestId('crew-collaboration-panel');
    expect(panel.getAttribute('data-state')).toBe(state);
    expect(panel.getAttribute('aria-busy')).toBe('false');
    expect(screen.getByText(projection(state).goal)).toBeTruthy();
    expect(container.querySelector('svg[fill="none"]')).toBeTruthy();
    if (state === 'executing') {
      expect(screen.getByTestId('crew-session-active-child').className).toContain('crew-session-active');
    }
    if (state === 'verifying') expect(panel.innerHTML).toContain('crew-session-verification');
    if (state === 'failed') expect(screen.queryByTestId('crew-session-active-child')).toBeNull();
  });

  it('renders progress, blocker and result commands through typed callbacks', async () => {
    const onRetry = vi.fn();
    stubFetch({ session: projection('blocked_needs_captain') });
    const view = render(<CrewCollaborationPanel threadId="t1" parentId="p1" onRetryBlockedWork={onRetry} />);
    expect(await screen.findByText('1/4')).toBeTruthy();
    const retry = screen.getByRole('button', { name: 'Retry blocked CrewSession work' });
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledWith(projection('blocked_needs_captain'), retry);

    view.unmount();
    stubFetch({ session: projection('done') });
    const onArtifact = vi.fn();
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" onOpenResultArtifact={onArtifact} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Open CrewSession result artifact' }));
    expect(onArtifact).toHaveBeenCalledWith('artifact-1', projection('done'));
    expect(screen.getByTestId('crew-session-verification').textContent).toContain('94%');
  });

  it('shows a stable aria-busy placeholder during the initial uncached load', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    expect(screen.getByTestId('crew-session-loading').getAttribute('aria-busy')).toBe('true');
  });

  it('renders 404 as a non-alert empty state', async () => {
    stubFetch({}, 404);
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    expect(await screen.findByTestId('crew-session-empty')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('renders an alert with keyboard-focusable Retry on an uncached error', async () => {
    stubFetch({}, 503);
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    const alert = await screen.findByRole('alert');
    const retry = screen.getByRole('button', { name: 'Retry' });
    retry.focus();
    expect(alert).toBeTruthy();
    expect(retry).toHaveFocus();
  });

  it('retains cached content on error and retries without overlapping requests', async () => {
    const cached = projection('executing');
    useStore.getState().hydrateCrewSession('p1', cached);
    let resolveRetry: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) } as Response)
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveRetry = resolve; }));
    vi.stubGlobal('fetch', fetchMock);
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByText(cached.goal)).toBeTruthy();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('last known state');
    const retry = screen.getByRole('button', { name: 'Retry' });
    fireEvent.click(retry);
    fireEvent.click(retry);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveRetry?.({ ok: true, status: 200, json: async () => ({ session: cached }) } as Response);
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('includes wrapping, reduced-motion, focus and no-emoji guards', async () => {
    stubFetch({ session: projection('blocked_needs_captain') });
    const { container } = render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    const panel = await screen.findByTestId('crew-collaboration-panel');
    const goal = screen.getByText(projection('blocked_needs_captain').goal);
    expect((goal as HTMLElement).style.overflowWrap).toBe('anywhere');
    expect(panel.innerHTML).toContain('@media (prefers-reduced-motion: reduce)');
    expect(panel.innerHTML).toContain('focus-visible');
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });

  it('preserves the legacy AD-862 tree rendering', async () => {
    stubFetch({
      parent: legacyItem('p1', 'Legacy goal', null),
      children: [legacyChild()],
      count: 1,
    });
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    expect(await screen.findByText('Legacy goal')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-card').className).toContain('crew-subtask-pulse');
  });

  it('reacts to an externally hydrated owned session while its GET is pending', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    expect(screen.getByTestId('crew-session-loading')).toBeTruthy();

    act(() => {
      useStore.getState().hydrateCrewSession('p1', projection('executing'));
    });

    expect(await screen.findByText(projection('executing').goal)).toBeTruthy();
    const panel = screen.getByTestId('crew-collaboration-panel');
    expect(panel.getAttribute('data-state')).toBe('executing');
    expect(panel.getAttribute('aria-busy')).toBe('true');
  });

  it('drops an old response resolved in the same act as a room switch', async () => {
    const oldProjection = projection('executing');
    const nextProjection = {
      ...projection('discussing'),
      task_id: 'p2',
      thread_id: 't2',
      goal: 'Owned room two goal',
    };
    let resolveOld: ((value: Response) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn((url: RequestInfo | URL) => {
      if (String(url).endsWith('/p1')) {
        return new Promise<Response>(resolve => { resolveOld = resolve; });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ session: nextProjection }),
      } as Response);
    }));
    const view = render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));

    await act(async () => {
      resolveOld?.({
        ok: true,
        status: 200,
        json: async () => ({ session: oldProjection }),
      } as Response);
      view.rerender(<CrewCollaborationPanel threadId="t2" parentId="p2" />);
    });

    expect(await screen.findByText(nextProjection.goal)).toBeTruthy();
    expect(useStore.getState().crewSessionsByParent.has('p1')).toBe(false);
    expect(useStore.getState().crewSessionsByParent.get('p2')).toEqual(nextProjection);
  });

  it('drops an old response and starts a current request after an A to B to A render cycle', async () => {
    const staleProjection = projection('executing');
    const freshProjection = { ...projection('discussing'), goal: 'Fresh room A goal' };
    let resolveOld: ((value: Response) => void) | undefined;
    let resolveFresh: ((value: Response) => void) | undefined;
    let roomACalls = 0;
    vi.stubGlobal('fetch', vi.fn((url: RequestInfo | URL) => {
      if (String(url).endsWith('/p1')) {
        roomACalls += 1;
        return new Promise<Response>(resolve => {
          if (roomACalls === 1) resolveOld = resolve;
          else resolveFresh = resolve;
        });
      }
      return new Promise<Response>(() => {});
    }));
    const view = render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));

    await act(async () => {
      view.rerender(<CrewCollaborationPanel threadId="t2" parentId="p2" />);
    });
    await act(async () => {
      resolveOld?.({
        ok: true,
        status: 200,
        json: async () => ({ session: staleProjection }),
      } as Response);
      view.rerender(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    });

    expect(useStore.getState().crewSessionsByParent.has('p1')).toBe(false);
    expect(screen.getByTestId('crew-session-loading')).toBeTruthy();
    await waitFor(() => expect(resolveFresh).toBeTypeOf('function'));

    await act(async () => {
      resolveFresh?.({
        ok: true,
        status: 200,
        json: async () => ({ session: freshProjection }),
      } as Response);
    });

    expect(await screen.findByText(freshProjection.goal)).toBeTruthy();
    expect(useStore.getState().crewSessionsByParent.get('p1')).toEqual(freshProjection);
  });

  it('stacks from observed 420 and 320 pixel host widths beside an expanded rail', async () => {
    let resize: ResizeObserverCallback | undefined;
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resize = callback; }
      observe(): void {}
      disconnect(): void {}
      unobserve(): void {}
    });
    stubFetch({ session: projection('executing') });
    render(
      <div style={{ display: 'flex', width: 420 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <CrewCollaborationPanel threadId="t1" parentId="p1" />
        </div>
        <aside data-testid="expanded-rail" style={{ flex: '0 0 100px', width: 100 }} />
      </div>,
    );
    const panel = await screen.findByTestId('crew-collaboration-panel');
    const grid = panel.querySelector('.crew-session-grid') as HTMLElement;

    act(() => {
      resize?.([{ contentRect: { width: 420 } } as ResizeObserverEntry], {} as ResizeObserver);
    });
    expect(panel.getAttribute('data-layout')).toBe('stacked');
    expect(grid.style.gridTemplateColumns).toBe('minmax(0, 1fr)');
    expect(getComputedStyle(panel).minHeight).toBe('220px');
    expect(screen.getByTestId('expanded-rail')).toBeTruthy();

    act(() => {
      resize?.([{ contentRect: { width: 320 } } as ResizeObserverEntry], {} as ResizeObserver);
    });
    expect(panel.getAttribute('data-layout')).toBe('stacked');
    expect(grid.children).toHaveLength(2);
    expect(Array.from(grid.children).every(child => (child as HTMLElement).style.position !== 'absolute')).toBe(true);
  });
});
