import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';

describe('BillDashboard store (AD-618d)', () => {
  beforeEach(() => {
    useStore.setState({
      billDefinitions: [],
      billInstances: [],
      billSelectedInstanceId: null,
    });
  });

  it('fetchBillDefinitions populates state', async () => {
    const mockDef = {
      bill_id: 'general_quarters',
      title: 'General Quarters',
      description: 'test',
      version: 1,
      activation: { trigger: 'manual', authority: 'captain' },
      roles: [],
      steps: [],
      step_count: 0,
      role_count: 0,
    };
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ definitions: [mockDef] }),
    }) as Response;

    await useStore.getState().fetchBillDefinitions();
    expect(useStore.getState().billDefinitions).toHaveLength(1);
    expect(useStore.getState().billDefinitions[0].bill_id).toBe('general_quarters');
  });

  it('fetchBillInstances populates state', async () => {
    const mockInst = {
      id: 'inst001',
      bill_id: 'general_quarters',
      bill_title: 'General Quarters',
      bill_version: 1,
      status: 'active',
      activated_by: 'captain',
      activated_at: 1000,
      completed_at: null,
      activation_data: {},
      role_assignments: {},
      step_states: {},
    };
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ instances: [mockInst] }),
    }) as Response;

    await useStore.getState().fetchBillInstances();
    expect(useStore.getState().billInstances).toHaveLength(1);
    expect(useStore.getState().billInstances[0].id).toBe('inst001');
  });

  it('selectBillInstance toggles selection', () => {
    useStore.getState().selectBillInstance('inst001');
    expect(useStore.getState().billSelectedInstanceId).toBe('inst001');

    useStore.getState().selectBillInstance(null);
    expect(useStore.getState().billSelectedInstanceId).toBeNull();
  });
});
