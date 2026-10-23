/**
 * AD-1347 S3 A2 (F19): the HXI reads every shared action-payload row as Python does. The expected answers are
 * Python's: tests/test_ad1347_s3_execution.py (X22) asserts each row through the real `can_fulfil_request` and
 * `agent_work_call`. A row's `fill` is applied here exactly as X22 applies it.
 */
import { describe, expect, it } from 'vitest';
import { isAgentWorkApproval, isCapabilityRequestView, parseCapabilityDecision } from '../capabilityApprovals';
import type { CapabilityApprovalView } from '../types';
import table from '../../../e2e/fixtures/ad1347-action-payload-rows.json';

interface Row {
  name: string;
  kind: string;
  work_item_id: string | null;
  payload: Record<string, unknown> | null;
  fill?: { field: string; chars: number };
  fulfillable: boolean;
  agent_work_call: boolean;
}

const rows = table.rows as unknown as Row[];

function view(row: Row, status: CapabilityApprovalView['status'], retry: boolean): CapabilityApprovalView {
  const payload = row.payload === null ? null : structuredClone(row.payload);
  let workItemId = row.work_item_id;
  if (row.fill && payload !== null) {
    const text = 'x'.repeat(row.fill.chars);
    if (row.fill.field === 'work_item_id') {
      workItemId = text;
      payload.scope_key = 'agent_work:' + text;
    } else if (row.fill.field === 'note') {
      (payload.params as Record<string, unknown>).note = text;
    } else {
      payload[row.fill.field] = text;
    }
  }
  return {
    id: '00000000-0000-0000-0000-000000000009', agent_id: 'forge-1', kind: row.kind, target: 'hull_survey',
    rationale: 'shared row', work_item_id: workItemId, status, created_at: 1000,
    decided_at: status === 'pending' ? null : 1000, decided_by: status === 'pending' ? '' : 'captain',
    decision_reason: '', payload, can_retry_fulfilment: retry,
  };
}

describe('AD-1347 A2 shared action-payload rows', () => {
  it('keeps an approved row retryable exactly when Python can fulfil it', () => {
    expect(rows.length).toBeGreaterThan(30);
    for (const row of rows) {
      expect([row.name, isCapabilityRequestView(view(row, 'approved', row.fulfillable))]).toEqual([row.name, true]);
      expect([row.name, isCapabilityRequestView(view(row, 'approved', !row.fulfillable))]).toEqual([row.name, false]);
      expect([row.name, isAgentWorkApproval(view(row, 'pending', false))]).toEqual([row.name, row.agent_work_call]);
    }
  });

  it('confirms a fulfilled decision exactly for the rows Python can fulfil', () => {
    for (const row of rows) {
      const pending = view(row, 'pending', false);
      let confirmed = true;
      try {
        parseCapabilityDecision({ request: view(row, 'fulfilled', false), standing_rule: null, fulfilled: true }, pending, true);
      } catch {
        confirmed = false;
      }
      expect([row.name, confirmed]).toEqual([row.name, row.fulfillable]);
    }
  });
});
