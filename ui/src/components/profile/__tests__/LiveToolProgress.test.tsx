import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveToolProgress } from '../LiveToolProgress';
import { useStore } from '../../../store/useStore';
import { useSettingsStore, type ConfigSnapshot } from '../../../store/useSettingsStore';
import { getOrCreateAgentThread, getThread } from '../../sidebar/threadApi';

const generation = 'a'.repeat(32);
function config(enabled: unknown): ConfigSnapshot {
  return {
    config: { agentic_loop: { event_correlation_enabled: enabled } }, secret_present: {},
    sections: [], domain_counts: {}, domain_order: [], section_count: 0, config_path: '',
    uptime_seconds: 0, csrf_token: '',
  };
}
function emit(completed = false, extra: Record<string, unknown> = {}): void {
  useStore.getState().handleEvent({
    type: completed ? 'agentic_tool_call_completed' : 'agentic_tool_call_started',
    data: {
      thread_id: 'room', agent_id: 'crew', run_id: 'b'.repeat(32), iteration: 1,
      tool_call_index: 0, tool_call_id: 'call', tool_id: 'read_file',
      ...(completed ? { is_error: false, duration_ms: 2 } : {}), ...extra,
    },
    stream: { generation, sequence: useStore.getState().liveSequence + 1 }, timestamp: 1,
  });
}
beforeEach(() => {
  useStore.setState(useStore.getInitialState(), true);
  useStore.getState().handleEvent({
    type: 'state_snapshot', data: {
      agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
    }, timestamp: 1, stream: { generation, sequence: 0 },
  });
  useStore.getState().setConnected(true);
  useSettingsStore.setState({ ...useSettingsStore.getInitialState(), loaded: true, snapshot: config(true) }, true);
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('No ambient transport')));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useStore.setState(useStore.getInitialState(), true);
  useSettingsStore.setState(useSettingsStore.getInitialState(), true);
});

describe('honest accessible tool observations', () => {
  it('shows unknown association and unknown configuration without claiming idle', () => {
    useSettingsStore.setState({ snapshot: config(undefined) });
    render(<LiveToolProgress threadId={null} participantIds={null} />);
    expect(screen.getByRole('region', { name: 'Live tool progress' })).toHaveTextContent('association unverified');
    expect(screen.getByText(/availability is unknown/)).toBeInTheDocument();
    expect(screen.queryByText(/0%|100%|cancelled|task succeeded/i)).not.toBeInTheDocument();
  });
  it('explains saved OFF and restart prerequisites', () => {
    useSettingsStore.setState({ snapshot: config(false) });
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    expect(screen.getByText(/off in saved settings/)).toHaveTextContent('restart the runtime');
    expect(screen.getByText(/No tool activity observed/)).toBeInTheDocument();
  });
  it('does not treat saved ON as evidence of activity or current runtime readiness', () => {
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    expect(screen.getByText(/Saved configuration is not activity evidence/)).toHaveTextContent('restart');
    expect(screen.queryByText('Start observed')).not.toBeInTheDocument();
  });
  it('updates the visible live summary from started to completed while details stay closed', () => {
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    act(() => emit());
    const details = screen.getByText(/Tool activity details/).closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(details).not.toContainElement(status);
    expect(status).toBeVisible();
    expect(status).toHaveTextContent('Tool observations: 1 started, 0 completed, 0 errors, 0 completion unconfirmed.');

    act(() => emit(true));
    expect(details).not.toHaveAttribute('open');
    expect(status).toBeVisible();
    expect(status).toHaveTextContent('Tool observations: 0 started, 1 completed, 0 errors, 0 completion unconfirmed.');

    act(() => {
      emit(false, { tool_call_index: 1 });
      emit(true, { tool_call_index: 1 });
    });
    expect(details).not.toHaveAttribute('open');
    expect(status).toBeVisible();
    expect(status).toHaveTextContent('Tool observations: 0 started, 2 completed, 0 errors, 0 completion unconfirmed.');
    expect(status).not.toHaveTextContent(/task|success|succeeded|delivered|100%/i);
  });
  it('counts a tool error separately from completed observations while details stay closed', () => {
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    act(() => emit());
    const status = screen.getByRole('status');
    const details = screen.getByText(/Tool activity details/).closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(status).toHaveTextContent('Tool observations: 1 started, 0 completed, 0 errors, 0 completion unconfirmed.');

    act(() => emit(true, { is_error: true }));
    expect(details).not.toHaveAttribute('open');
    expect(status).toBeVisible();
    expect(status).toHaveTextContent('Tool observations: 0 started, 0 completed, 1 errors, 0 completion unconfirmed.');
    expect(status).not.toHaveTextContent(/task|success|succeeded|delivered|100%/i);
  });
  it('does not count started, errored, or timed-out observations as completed', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1000);
    emit();
    emit(true);
    emit(false, { tool_call_index: 1 });
    emit(true, { tool_call_index: 1, is_error: true });
    emit(false, { tool_call_index: 2 });
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    const status = screen.getByRole('status');
    const details = screen.getByText(/Tool activity details/).closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(status).toHaveTextContent('Tool observations: 1 started, 1 completed, 1 errors, 0 completion unconfirmed.');

    act(() => vi.advanceTimersByTime(30_000));
    expect(details).not.toHaveAttribute('open');
    expect(status).toBeVisible();
    expect(status).toHaveTextContent('Tool observations: 0 started, 1 completed, 1 errors, 1 completion unconfirmed.');
    expect(status).not.toHaveTextContent(/task|success|succeeded|delivered|100%/i);
  });
  it('keeps verified observations visible under a stale OFF snapshot and distinguishes errors', () => {
    useSettingsStore.setState({ snapshot: config(false) });
    emit();
    emit(true, { tool_call_index: 1, tool_id: 'write_file', is_error: true });
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    fireEvent.click(screen.getByText(/Tool activity details/));
    const list = screen.getByRole('list', { name: 'Observed tool calls' });
    expect(within(list).getByText('Start observed')).toBeInTheDocument();
    expect(within(list).getByText('Tool error')).toBeInTheDocument();
    expect(within(list).getByText(/Completion arrived without/)).toBeInTheDocument();
    expect(screen.getByText(/not confirmation that the task succeeded/)).toBeInTheDocument();
    expect(list).not.toHaveTextContent('crew');
  });
  it('ages a start to completion unconfirmed at the actual 30-second deadline', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1000);
    emit();
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    act(() => vi.advanceTimersByTime(29_999));
    expect(screen.getByText('Start observed')).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByText('Completion unconfirmed')).toBeInTheDocument();
    act(() => emit(true));
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });
  it('preserves terminal facts and exposes disconnected/incomplete delivery', () => {
    emit(true);
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    act(() => useStore.getState().setConnected(false));
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText(/Event stream disconnected/)).toHaveTextContent('Delivery is incomplete');
    expect(screen.getByText(/Earlier observation/)).toBeInTheDocument();
  });
  it('discloses bounded retention loss in the rendered component', () => {
    for (let i = 0; i < 65; i += 1) emit(false, { tool_call_index: i });
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    expect(screen.getByText(/call records omitted/)).toHaveTextContent('0 run records and 1 call records omitted');
    expect(screen.getAllByRole('listitem', { hidden: true })).toHaveLength(64);
  });
  it('reuses idempotent configuration loading without resetting saved settings drafts', () => {
    const draft = { 'agentic_loop.event_correlation_enabled': false };
    useSettingsStore.setState({ draft, draftCount: 1, applyStatus: 'restart_required' });
    const mounted = render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    mounted.rerender(<LiveToolProgress threadId="elsewhere" participantIds={['other']} />);
    expect(fetch).not.toHaveBeenCalled();
    expect(useSettingsStore.getState()).toMatchObject({ draft, draftCount: 1, applyStatus: 'restart_required' });
  });
  it('shows config failure as unknown and never renders the raw failure detail', async () => {
    useSettingsStore.setState({ loaded: false, snapshot: null });
    render(<LiveToolProgress threadId="room" participantIds={['crew']} />);
    await waitFor(() => expect(useSettingsStore.getState().loading).toBe(false));
    expect(fetch).toHaveBeenCalledWith('/api/config');
    expect(screen.getByText(/availability is unknown/)).toBeInTheDocument();
    expect(screen.getByRole('region')).not.toHaveTextContent('No ambient transport');
  });
});

describe('existing thread helpers optional abort', () => {
  it('preserves both old no-signal fetch argument shapes exactly', async () => {
    const thread = { id: 'room', participants: ['crew'] };
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(thread)));
    expect(await getThread('room/a')).toEqual(thread);
    expect(fetch).toHaveBeenLastCalledWith('/api/threads/room%2Fa');
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(thread)));
    expect(await getOrCreateAgentThread('crew/a')).toEqual(thread);
    expect(fetch).toHaveBeenLastCalledWith('/api/agent/crew%2Fa/thread', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    });
  });
  it('adds only the supplied abort signal to each existing helper', async () => {
    const signal = new AbortController().signal;
    vi.mocked(fetch).mockResolvedValue(new Response('{"id":"room"}'));
    await getThread('room', signal);
    expect(fetch).toHaveBeenLastCalledWith('/api/threads/room', { signal });
    vi.mocked(fetch).mockResolvedValue(new Response('{"id":"room"}'));
    await getOrCreateAgentThread('crew', signal);
    expect(fetch).toHaveBeenLastCalledWith('/api/agent/crew/thread', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    });
  });
  it.each(['http', 'empty', 'throw'])('keeps helper failure degradation unchanged: %s', async failure => {
    const response = () => failure === 'throw'
      ? Promise.reject(new Error('local refusal'))
      : Promise.resolve(new Response(failure === 'empty' ? 'null' : '{}', { status: failure === 'http' ? 503 : 200 }));
    vi.mocked(fetch).mockImplementation(response);
    expect(await getThread('')).toBeNull();
    expect(await getOrCreateAgentThread('')).toBeNull();
  });
});
