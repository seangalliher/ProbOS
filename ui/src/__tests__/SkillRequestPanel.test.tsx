/**
 * AD-908: SkillRequestPanel tests.
 *
 * The panel is deps-injectable: a `fetchImpl` prop replaces the global fetch,
 * so these tests inject a mock rather than stubbing globals.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';
import SkillRequestPanel from '../components/skill/SkillRequestPanel';

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

function okJson(body: unknown) {
  return { ok: true, json: async () => body } as Response;
}

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

  it('renders_null_when_no_pending_requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ requests: [] }));

    render(<SkillRequestPanel fetchImpl={fetchMock as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('skill-request-panel')).toBeNull();
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
