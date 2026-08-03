/**
 * BF-710 defect 3: both approval panels must actually poll.
 *
 * Each module docstring claimed the panel "polls /api/…?status=pending". Neither
 * did: `load` was invoked from a mount effect whose only dependency was a stable
 * `useCallback`, so it ran exactly once. A request filed after the Captain's
 * browser loaded would never appear — which, for a surface whose entire job is
 * to show requests as they arrive, is the same blackout as not being mounted.
 *
 * These tests drive the clock, so they fail if the interval is removed, if its
 * cadence drifts, or if it survives unmount.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';
import CapabilityRequestPanel from '../components/capability/CapabilityRequestPanel';
import SkillRequestPanel from '../components/skill/SkillRequestPanel';

/** Must match POLL_INTERVAL_MS in both panels. */
const POLL_MS = 10000;

const CAPABILITY_REQUEST = {
  id: 'req-filed-after-mount',
  agent_id: 'agent-1',
  kind: 'continue',
  target: 'continue: summarise the incident log',
  rationale: 'cut off after 3 passes',
  work_item_id: null,
  status: 'pending',
  created_at: 1.0,
  decided_at: null,
  decided_by: '',
  decision_reason: '',
};

const SKILL_REQUEST = {
  id: 'sr-filed-after-mount',
  agent_id: 'agent-1',
  skill_id: 'summarization',
  skill_label: 'Summarization',
  source: 'self',
  justification: 'condense long reports',
  status: 'requested',
  linked_simulation_id: null,
  created_at: 1.0,
  decided_at: null,
  decided_by: '',
  decision_reason: '',
  pre_metric: null,
  post_metric: null,
};

function okJson(body: unknown) {
  return { ok: true, json: async () => body } as Response;
}

/** Empty first, then one pending request — a request filed after mount. */
function filedAfterMount(request: unknown) {
  let calls = 0;
  return vi.fn(async () => {
    calls += 1;
    return okJson({ requests: calls === 1 ? [] : [request] });
  });
}

async function tick(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('approval panel polling (BF-710)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('capability panel shows a request filed after mount on the next poll', async () => {
    const fetchMock = filedAfterMount(CAPABILITY_REQUEST);
    vi.stubGlobal('fetch', fetchMock);

    render(<CapabilityRequestPanel />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('capability-request-card')).toBeNull();

    await tick(POLL_MS);

    await waitFor(() =>
      expect(screen.getByTestId('capability-request-card')).toBeTruthy(),
    );
    expect(screen.getByText('cut off after 3 passes')).toBeTruthy();
  });

  it('skill panel shows a request filed after mount on the next poll', async () => {
    const fetchMock = filedAfterMount(SKILL_REQUEST);

    render(<SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('skill-request-card')).toBeNull();

    await tick(POLL_MS);

    await waitFor(() =>
      expect(screen.getByTestId('skill-request-card')).toBeTruthy(),
    );
    expect(screen.getByText('condense long reports')).toBeTruthy();
  });

  it('capability panel clears its interval on unmount', async () => {
    const fetchMock = vi.fn(async () => okJson({ requests: [] }));
    vi.stubGlobal('fetch', fetchMock);

    const view = render(<CapabilityRequestPanel />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.unmount();
    await tick(POLL_MS * 5);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('skill panel clears its interval on unmount', async () => {
    const fetchMock = vi.fn(async () => okJson({ requests: [] }));

    const view = render(
      <SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.unmount();
    await tick(POLL_MS * 5);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('capability panel polls once per interval, not once per render', async () => {
    /* BF-710: an unstable effect dependency would re-arm the interval on every
     * render and turn a poll into a fetch storm. Three intervals => four calls
     * (the mount call plus one per interval). */
    const fetchMock = vi.fn(async () => okJson({ requests: [CAPABILITY_REQUEST] }));
    vi.stubGlobal('fetch', fetchMock);

    render(<CapabilityRequestPanel />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await tick(POLL_MS * 3);

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('skill panel polls once per interval on the default (uninjected) fetch path', async () => {
    /* The production path passes no fetchImpl. Before BF-710 that branch built a
     * new function every render, so `load` and the effect were unstable — a
     * defect no existing test could see, because every existing test injects
     * fetchImpl and therefore only exercised the stable branch. */
    const fetchMock = vi.fn(async () => okJson({ requests: [SKILL_REQUEST] }));
    vi.stubGlobal('fetch', fetchMock);

    render(<SkillRequestPanel />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await tick(POLL_MS * 3);

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('both panels still render null once loaded with no pending requests', async () => {
    const capabilityFetch = vi.fn(async () => okJson({ requests: [] }));
    vi.stubGlobal('fetch', capabilityFetch);
    const skillFetch = vi.fn(async () => okJson({ requests: [] }));

    render(
      <>
        <CapabilityRequestPanel />
        <SkillRequestPanel fetchImpl={skillFetch as unknown as typeof fetch} />
      </>,
    );

    await waitFor(() => {
      expect(screen.queryByTestId('capability-request-panel')).toBeNull();
      expect(screen.queryByTestId('skill-request-panel')).toBeNull();
    });
  });
});
