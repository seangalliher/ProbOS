/**
 * AD-745: AgentActionLog vitest tests.
 *
 * Six tests covering: collapsed-by-default, expand toggle, tier-glyph
 * stroke density, ABORT POST wiring, pulse animation on pending status,
 * frame-thumbnail rendering.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AgentActionLog, type ActionEntry } from '../AgentActionLog';

const TIER2_ACK: ActionEntry = {
  action_id: 'a-1',
  agent_id: 'counselor',
  thread_id: 'tt',
  verb: 'click',
  raw_intent: 'submit form',
  tier: 2,
  status: 'ack_pending',
  page_url: 'https://example.com/form',
  before_frame_ref: null,
  after_frame_ref: null,
};

const TIER1_EXECUTED: ActionEntry = {
  ...TIER2_ACK,
  action_id: 'a-2',
  verb: 'screenshot',
  raw_intent: '',
  tier: 1,
  status: 'executed',
  after_frame_ref: 'sha-after',
};

const TIER3_CONFIRM: ActionEntry = {
  ...TIER2_ACK,
  action_id: 'a-3',
  verb: 'compute_use_click',
  raw_intent: 'pay button',
  tier: 3,
  status: 'confirm_pending',
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('AgentActionLog (AD-745)', () => {
  it('renders collapsed by default with the entry count', async () => {
    const fetcher = vi.fn(async () => [TIER2_ACK]);
    render(<AgentActionLog threadId="tt" fetcher={fetcher} pollIntervalMs={1_000_000} />);
    await waitFor(() => {
      expect(screen.getByTestId('agent-action-log-toggle')).toBeTruthy();
    });
    // Entries list NOT rendered while collapsed.
    expect(screen.queryByTestId('agent-action-log-entries')).toBeNull();
  });

  it('expand toggle reveals entry rows', async () => {
    const fetcher = vi.fn(async () => [TIER2_ACK]);
    render(<AgentActionLog threadId="tt" fetcher={fetcher} pollIntervalMs={1_000_000} />);
    await waitFor(() => screen.getByTestId('agent-action-log-toggle'));
    fireEvent.click(screen.getByTestId('agent-action-log-toggle'));
    await waitFor(() => screen.getByTestId('agent-action-log-entries'));
    expect(screen.getByTestId('agent-action-entry-a-1')).toBeTruthy();
  });

  it('tier glyph stroke density reflects classified tier', async () => {
    const fetcher = vi.fn(async () => [TIER1_EXECUTED, TIER2_ACK, TIER3_CONFIRM]);
    render(<AgentActionLog threadId="tt" fetcher={fetcher} pollIntervalMs={1_000_000} />);
    await waitFor(() => screen.getByTestId('agent-action-log-toggle'));
    fireEvent.click(screen.getByTestId('agent-action-log-toggle'));
    await waitFor(() => screen.getByTestId('action-tier-glyph-1'));
    expect(screen.getByTestId('action-tier-glyph-1')).toBeTruthy();
    expect(screen.getByTestId('action-tier-glyph-2')).toBeTruthy();
    expect(screen.getByTestId('action-tier-glyph-3')).toBeTruthy();
  });

  it('ABORT button POSTs to /abort endpoint', async () => {
    const fetcher = vi.fn(async () => [TIER2_ACK]);
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true }),
    } as unknown as Response);
    render(<AgentActionLog threadId="tt" fetcher={fetcher} pollIntervalMs={1_000_000} />);
    await waitFor(() => screen.getByTestId('agent-action-log-toggle'));
    fireEvent.click(screen.getByTestId('agent-action-log-toggle'));
    await waitFor(() => screen.getByTestId('agent-action-abort-a-1'));
    fireEvent.click(screen.getByTestId('agent-action-abort-a-1'));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.filter(
        (c) => String(c[0]).includes('/abort'),
      );
      expect(calls.length).toBeGreaterThan(0);
      expect(String(calls[0][0])).toBe('/api/browser/actions/a-1/abort');
    });
  });

  it('pulse animation applied on ack_pending / confirm_pending', async () => {
    const fetcher = vi.fn(async () => [TIER2_ACK, TIER3_CONFIRM]);
    render(<AgentActionLog threadId="tt" fetcher={fetcher} pollIntervalMs={1_000_000} />);
    await waitFor(() => screen.getByTestId('agent-action-log-toggle'));
    fireEvent.click(screen.getByTestId('agent-action-log-toggle'));
    await waitFor(() => screen.getByTestId('action-status-ack_pending'));
    expect(screen.getByTestId('action-status-ack_pending').getAttribute('data-pulsing')).toBe('true');
    expect(screen.getByTestId('action-status-confirm_pending').getAttribute('data-pulsing')).toBe('true');
  });

  it('frame indicator renders when before/after refs present', async () => {
    const fetcher = vi.fn(async () => [TIER1_EXECUTED]);
    render(<AgentActionLog threadId="tt" fetcher={fetcher} pollIntervalMs={1_000_000} />);
    await waitFor(() => screen.getByTestId('agent-action-log-toggle'));
    fireEvent.click(screen.getByTestId('agent-action-log-toggle'));
    await waitFor(() => screen.getByTestId('agent-action-frames-a-2'));
    expect(screen.getByTestId('agent-action-frames-a-2')).toBeTruthy();
  });
});
