/**
 * AD-857: CapabilityRequestPanel tests.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';
import CapabilityRequestPanel from '../components/capability/CapabilityRequestPanel';

const PENDING = {
  requests: [
    {
      id: 'req-1',
      agent_id: 'agent-1',
      kind: 'install',
      target: 'numpy',
      rationale: 'need arrays',
      work_item_id: 'wi-123456789012',
      status: 'pending',
      created_at: 1.0,
      decided_at: null,
      decided_by: '',
      decision_reason: '',
    },
  ],
};

describe('CapabilityRequestPanel (AD-857)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => cleanup());

  it('renders_pending_card_with_rationale_and_buttons', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => PENDING,
    }));

    render(<CapabilityRequestPanel />);

    await waitFor(() => {
      expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    });
    expect(screen.getByText('need arrays')).toBeTruthy();
    expect(screen.getByText('Approve')).toBeTruthy();
    expect(screen.getByText('Deny')).toBeTruthy();
    expect(screen.getByTestId('linked-work-item')).toBeTruthy();
  });

  it('approve_click_posts_to_decide_endpoint', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => PENDING })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ request: {} }) });
    vi.stubGlobal('fetch', fetchMock);

    render(<CapabilityRequestPanel />);

    await waitFor(() => {
      expect(screen.getByText('Approve')).toBeTruthy();
    });
    fireEvent.click(screen.getByText('Approve'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/capability-requests/req-1/decide',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.approve).toBe(true);
  });
});
