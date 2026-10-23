/**
 * AD-1347 S3 A2 (F18): the card says what approving an agent-work call does and offers no standing approval for it;
 * an ordinary action keeps the ordinary copy and the standing choice (ApprovalWave.test.tsx pins that copy too).
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { CapabilityApprovalView } from '../../../store/types';
import { useSettingsStore } from '../../../store/useSettingsStore';
import { CapabilityRequestCard } from '../CapabilityRequestCard';
import wire from '../../../../e2e/fixtures/ad1347-agent-work-approvals.json';

const AGENT_WORK = wire.pending.requests[0] as unknown as CapabilityApprovalView;
const ORDINARY = {
  ...AGENT_WORK, id: '00000000-0000-0000-0000-000000000003', target: 'browser.click', work_item_id: null,
  payload: { tool_id: 'browser', action: 'click', params: { selector: '#send' },
    scope_key: 'example.test', session_id: null, thread_id: 'thread-a' },
} as CapabilityApprovalView;

beforeEach(() => { useSettingsStore.setState({ loaded: true, loading: false }); });
afterEach(() => { cleanup(); });

describe('AD-1347 agent-work approval card', () => {
  it('says an agent-work approval resumes its item and offers no standing approval; an ordinary action keeps both', () => {
    render(<CapabilityRequestCard requestId={AGENT_WORK.id} request={AGENT_WORK} />);
    expect(screen.queryByText(/does not replay the original action/)).toBeNull();
    expect(screen.getByText(/Approval resumes work item wi-agent-work-1\./)).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: 'Grant standing approval' })).toBeNull();
    cleanup();
    render(<CapabilityRequestCard requestId={ORDINARY.id} request={ORDINARY} />);
    expect(screen.getByText(/does not replay the original action/)).toBeTruthy();
    expect(screen.queryByText(/Approval resumes work item/)).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Grant standing approval' })).toBeTruthy();
  });
});
