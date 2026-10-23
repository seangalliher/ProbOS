/**
 * AD-1347 S3 A1 (F1): the HXI decoder accepts the approval route's real agent-work envelopes.
 * The fixture is asserted equal to the real Python route output by tests/test_ad1347_s3_execution.py (X13).
 */
import { describe, expect, it } from 'vitest';
import { isActionableCapabilityPayload, isCapabilityRequestView, parseCapabilityDecision } from '../capabilityApprovals';
import wire from '../../../e2e/fixtures/ad1347-agent-work-approvals.json';

describe('AD-1347 agent-work approval wire', () => {
  it('confirms the fulfilled approval of the agent-work call bound to its item', () => {
    expect(isActionableCapabilityPayload(wire.pending)).toBe(true);
    const [pending] = wire.pending.requests;
    if (!isCapabilityRequestView(pending)) throw new Error('Invalid Python pending fixture');
    const outcome = parseCapabilityDecision(wire.fulfilled, pending, true);
    expect(outcome.fulfilled).toBe(true);
    expect(outcome.request.status).toBe('fulfilled');
  });

  it('keeps an approved, unfulfilled agent-work call on the queue as retryable', () => {
    expect(isActionableCapabilityPayload(wire.approved)).toBe(true);
    expect(wire.approved.requests[0].can_retry_fulfilment).toBe(true);
  });

  it('refuses a retry flag on an agent-work call bound to another item or another action', () => {
    const [row] = wire.approved.requests;
    for (const changed of [
      { ...row, work_item_id: 'wi-other' },
      { ...row, payload: { ...row.payload, action: 'click' } },
    ]) expect(isCapabilityRequestView(changed)).toBe(false);
  });
});
