/**
 * AD-908: SkillRequestPanel tests.
 *
 * The panel is deps-injectable: a `fetchImpl` prop replaces the global fetch,
 * so these tests inject a mock rather than stubbing globals.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent, act } from '@testing-library/react';
import SkillRequestPanel from '../components/skill/SkillRequestPanel';
import { RESOURCE_TIMEOUT_MS } from '../utils/resourceState';

const PENDING = {
  requests: [
    {
      id: 'sr-1',
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
    },
  ],
};

function okJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const unavailable = () => okJson({
  detail: 'skill request store not available',
  availability: { state: 'unavailable', code: 'skill_requests.unavailable', message: 'Skill requests unavailable', retryable: true },
}, 503);

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('SkillRequestPanel (AD-908)', () => {
  afterEach(() => cleanup());

  it('renders_pending_card_with_justification_and_buttons', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson(PENDING));

    render(<SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByTestId('skill-request-card')).toBeTruthy();
    });
    expect(screen.getByText('condense long reports')).toBeTruthy();
    expect(screen.getByText('Summarization')).toBeTruthy();
    expect(screen.getByText('Approve')).toBeTruthy();
    expect(screen.getByText('Deny')).toBeTruthy();
    expect(screen.getByTestId('skill-request-status').textContent).toBe('requested');
  });

  it('approve_click_posts_approve_true_to_decide_endpoint', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson(PENDING))
      .mockResolvedValueOnce(okJson({ request: {} }));

    render(<SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByText('Approve')).toBeTruthy();
    });
    fireEvent.click(screen.getByText('Approve'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/skill-requests/sr-1/decide',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    const body = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
    expect(body.approve).toBe(true);
  });

  it('deny_without_reason_is_blocked_and_does_not_post', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson(PENDING));

    render(<SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByText('Deny')).toBeTruthy();
    });
    fireEvent.click(screen.getByText('Deny'));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
    });
    // Only the initial load fetch fired; no decide POST.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('renders_authoritative_empty_when_no_pending_requests', async () => {
    // Successful emptiness stays visible so it cannot be confused with a failed read.
    const fetchMock = vi.fn().mockResolvedValue(okJson({ requests: [] }));

    render(<SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />);

    expect(await screen.findByText('No skill requests pending.')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('skill-request-panel')).toBeTruthy();
  });

  it('contains_no_emoji_glyphs', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson(PENDING));

    const { container } = render(
      <SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('skill-request-card')).toBeTruthy();
    });
    const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F1E6}-\u{1F1FF}]/u;
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});

describe('issue #1368 standalone skill resource boundary', () => {
  const status = () => screen.getByRole('status', { name: 'Skill requests status' });
  const refresh = () => fireEvent.click(screen.getByRole('button', { name: 'Refresh skill requests' }));
  const tick = async (milliseconds: number): Promise<void> => {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
  };

  it('renders loading then unavailable, and manual refresh recovers with real route envelopes', async () => {
    let release!: (response: Response) => void;
    const transport = vi.fn<typeof fetch>()
      .mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }))
      .mockResolvedValueOnce(okJson(PENDING));
    render(<SkillRequestPanel fetchImpl={transport} />);
    expect(status()).toHaveTextContent('Loading.');
    expect(transport).toHaveBeenCalledTimes(1);
    await act(async () => { release(unavailable()); });
    expect(status()).toHaveTextContent('Unavailable. Retry the request.');
    expect(screen.queryByText('No skill requests pending.')).toBeNull();
    refresh();
    expect(await screen.findByText('Summarization')).toBeTruthy();
    expect(status()).toHaveTextContent('Available.');
  });

  it.each([
    [503, { detail: 'skill request store not available' }, 'Unavailable.'],
    [503, { detail: 'skill request store not available', availability: {
      state: 'disabled', code: 'skill_requests.disabled', message: 'Skill requests disabled', retryable: false,
    } }, 'Disabled. Review configuration with the operator.'],
    [401, { detail: 'secret' }, 'Access denied. Request appropriate access.'],
    [403, { detail: 'secret' }, 'Access denied. Request appropriate access.'],
    [500, { detail: 'private diagnostic' }, 'Request failed.'],
    [200, {}, 'Request failed.'],
    [200, { requests: null }, 'Request failed.'],
    [200, { requests: [{ id: 'invalid' }] }, 'Request failed.'],
  ])('classifies HTTP %s without hiding the panel', async (httpStatus, body, message) => {
    const transport = vi.fn<typeof fetch>().mockResolvedValue(okJson(body, httpStatus as number));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await waitFor(() => expect(status()).toHaveTextContent(message as string));
    expect(screen.getByTestId('skill-request-panel')).toBeTruthy();
    expect(status()).not.toHaveTextContent(/secret|diagnostic/);
    expect(screen.queryByText('No skill requests pending.')).toBeNull();
  });

  it('rejects malformed JSON in a successful response', async () => {
    const transport = vi.fn<typeof fetch>().mockResolvedValue(new Response('not JSON'));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await waitFor(() => expect(status()).toHaveTextContent('Request failed.'));
  });

  it.each([false, true])('retains a same-queue last-known snapshot, including empty=%s', async empty => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(okJson(empty ? { requests: [] } : PENDING))
      .mockImplementation(() => Promise.resolve(unavailable()));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await waitFor(() => expect(status()).toHaveTextContent(empty ? 'No skill requests pending.' : 'Available.'));
    refresh();
    await waitFor(() => expect(status()).toHaveTextContent('Unavailable.'));
    expect(status()).toHaveTextContent('Showing last-known skill requests; current count unknown.');
    expect(status()).toHaveTextContent('Last successful observation:');
    expect(screen.queryByText('No skill requests pending.')).toBeNull();
    expect(screen.queryAllByTestId('skill-request-card')).toHaveLength(empty ? 0 : 1);
  });

  it.each([401, 403])('clears cached skill content after HTTP %s', async httpStatus => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(okJson(PENDING))
      .mockResolvedValueOnce(okJson({ detail: 'denied' }, httpStatus));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await screen.findByText('Summarization');
    refresh();
    await waitFor(() => expect(status()).toHaveTextContent('Access denied.'));
    expect(screen.queryByText('Summarization')).toBeNull();
    expect(status()).not.toHaveTextContent('last-known');
  });

  it('retries at 10 and 30 seconds, then pauses until manual recovery', async () => {
    vi.useFakeTimers();
    const transport = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(unavailable()));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await tick(0);
    expect(transport).toHaveBeenCalledTimes(1);
    await tick(9_999);
    expect(transport).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(transport).toHaveBeenCalledTimes(2);
    await tick(19_999);
    expect(transport).toHaveBeenCalledTimes(2);
    await tick(1);
    expect(transport).toHaveBeenCalledTimes(3);
    await tick(90_000);
    expect(transport).toHaveBeenCalledTimes(3);
    transport.mockImplementation(() => Promise.resolve(okJson({ requests: [] })));
    refresh();
    await tick(0);
    expect(status()).toHaveTextContent('No skill requests pending.');
    await tick(10_000);
    expect(transport).toHaveBeenCalledTimes(5);
  });

  it.each([401, 403, 503])('stops immediately on denied or typed-disabled HTTP %s', async httpStatus => {
    vi.useFakeTimers();
    const transport = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(okJson({
      detail: 'unavailable', availability: {
        state: 'disabled', code: 'skill_requests.disabled', message: 'Disabled', retryable: false,
      },
    }, httpStatus)));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await tick(0);
    expect(status()).toHaveTextContent(httpStatus === 503 ? 'Disabled.' : 'Access denied.');
    await tick(120_000);
    expect(transport).toHaveBeenCalledTimes(1);
  });

  it('bounds a hung request before retrying and cancels the next request on unmount', async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const transport = vi.fn<typeof fetch>().mockImplementation((_input, init) => {
      expect(signals.every(signal => signal.aborted)).toBe(true);
      signals.push(init!.signal!);
      return new Promise<Response>(() => {});
    });
    const view = render(<SkillRequestPanel fetchImpl={transport} />);
    await tick(RESOURCE_TIMEOUT_MS - 1);
    expect(transport).toHaveBeenCalledTimes(1);
    await tick(2);
    expect(signals[0].aborted).toBe(true);
    expect(transport).toHaveBeenCalledTimes(2);
    view.unmount();
    await tick(120_000);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(transport).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not resurrect a decided row from an older GET and never retries POST', async () => {
    let release!: (response: Response) => void;
    let reads = 0;
    const transport = vi.fn<typeof fetch>().mockImplementation((_input, init) => {
      if (init?.method === 'POST') return Promise.resolve(okJson({ request: {} }));
      reads += 1;
      return reads === 1 ? Promise.resolve(okJson(PENDING))
        : new Promise<Response>(resolve => { release = resolve; });
    });
    const onDecided = vi.fn();
    render(<SkillRequestPanel fetchImpl={transport} onDecided={onDecided} />);
    await screen.findByText('Summarization');
    refresh();
    expect(reads).toBe(2);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledWith({ queue: 'skill', id: 'sr-1' }));
    expect(screen.queryByTestId('skill-request-card')).toBeNull();
    await act(async () => { release(okJson(PENDING)); });
    expect(screen.queryByTestId('skill-request-card')).toBeNull();
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });

  it('keeps a failed decision visible without automatically retrying the mutation', async () => {
    vi.useFakeTimers();
    const transport = vi.fn<typeof fetch>().mockImplementation((_input, init) => Promise.resolve(
      init?.method === 'POST' ? okJson({ detail: 'decision failed' }, 503) : okJson(PENDING),
    ));
    render(<SkillRequestPanel fetchImpl={transport} />);
    await tick(0);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick(0);
    expect(screen.getByRole('alert')).toHaveTextContent('decision failed (503)');
    await tick(60_000);
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    expect(screen.getByTestId('skill-request-card')).toBeTruthy();
  });
});
