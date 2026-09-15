import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Agent, AgentProfileData, AvatarDSLDict } from '../store/types';
import type { MemoryGraphResponse } from '../components/profile/memoryGraphTypes';
import telemetryFixture from '../../e2e/fixtures/issue1370-telemetry.json';

vi.mock('../components/profile/ProfileChatTab', () => ({ ProfileChatTab: () => <div>Chat body</div> }));
vi.mock('../components/profile/ProfileWorkTab', () => ({ ProfileWorkTab: () => null }));
vi.mock('../components/profile/ProfileServiceTab', () => ({ ProfileServiceTab: () => null }));
vi.mock('../components/profile/SelfImageTab', () => ({ SelfImageTab: () => null }));
vi.mock('../components/artifacts/ArtifactDrawer', () => ({ ArtifactDrawer: () => null }));
vi.mock('../components/profile/MemoryGraph3D', () => ({
  default: ({ data }: { data: MemoryGraphResponse }) => <div data-testid="graph-nodes">{data.nodes.map(node => node.label).join(',')}</div>,
}));
vi.mock('../components/profile/CrewAvatarPopout', () => ({
  CrewAvatarPopout: ({ agentId, onApproveDsl }: { agentId: string; onApproveDsl: (dsl: AvatarDSLDict) => Promise<void> }) =>
    <button onClick={() => void onApproveDsl({} as AvatarDSLDict)}>Approve {agentId}</button>,
}));
vi.mock('../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null), getAvailableVoices: vi.fn(() => []), speakResponse: vi.fn(),
}));

import { AgentProfilePanel } from '../components/profile/AgentProfilePanel';
import { ProfileMemoryTab } from '../components/profile/ProfileMemoryTab';
import { WelcomeOverlay } from '../components/WelcomeOverlay';
import { useStore } from '../store/useStore';

const INITIAL = useStore.getState();
const BASE_TIME = '2026-09-14T19:41:43.000Z';

function agent(id: string): Agent {
  return { id, agentType: 'counselor', callsign: id, displayName: id, pool: 'medical',
    state: 'active', confidence: 0.91, trust: 0.92, tier: 'domain', isCrew: true, position: [0, 0, 0] };
}

function profile(id = 'alpha', count: number | null = 196): AgentProfileData {
  const sample = new Date(Date.now()).toISOString();
  return { id, sovereignId: `sovereign-${id}`, agentType: 'counselor', callsign: id, displayName: id,
    rank: 'lieutenant', agencyLevel: 'autonomous', department: 'medical', personality: {}, specialization: [],
    trust: 0.73, trustHistory: [], confidence: 0.62, state: 'active', tier: 'domain', pool: 'medical',
    hebbianConnections: [], memoryCount: count, uptime: 120, proactiveCooldown: null, isCrew: true, visionCapable: false,
    memoryCountMetadata: { subjectId: `sovereign-${id}`, population: 'stored_agent_membership', unit: 'episodes',
      source: 'episodic_memory.count_for_agent', sampleStartedAt: sample, sampleCompletedAt: sample,
      status: count === null ? 'unavailable' : 'available' },
    uptimeMetadata: { subjectId: 'system', population: 'system_runtime', unit: 'seconds', source: 'runtime.get_uptime_seconds',
      sampleStartedAt: sample, sampleCompletedAt: sample, status: 'available' },
  };
}

function graph(shipWide = false, empty = false): MemoryGraphResponse {
  const sample = new Date(Date.now()).toISOString();
  return { nodes: empty ? [] : [{ id: shipWide ? 'other-episode' : 'own-episode', label: shipWide ? 'Other agent episode' : 'Own episode',
    timestamp: 100, importance: 5, activation: 0.5, channel: 'medical', department: 'medical',
    agent_ids: [shipWide ? 'sovereign-beta' : 'sovereign-alpha'], participants: [], source: 'test',
    reflection: '', user_input: 'Synthetic', color: '#52c474', size: 4 }], edges: [],
    meta: { agent_id: 'alpha', total_episodes: 196, nodes_shown: empty ? 0 : 1, ship_wide: shipWide,
      total_measurement: { subject_id: 'sovereign-alpha', population: 'stored_agent_membership', unit: 'episodes',
        source: 'episodic_memory.count_for_agent', sample_started_at: sample, sample_completed_at: sample, status: 'available' },
      selection: { subject_id: shipWide ? 'ship' : 'sovereign-alpha', population: shipWide ? 'registered_crew_bounded_graph' : 'agent_bounded_graph',
        unit: 'episodes', source: 'memory_graph.selection', status: 'available', sample_started_at: sample,
        sample_completed_at: sample, max_nodes: 200, time_range_hours: null, bounded: true } } };
}

interface PendingRead {
  url: string;
  signal: AbortSignal | null | undefined;
  resolve: (response: Response) => void;
  reject: (reason: Error) => void;
}

let reads: PendingRead[];
let visibility: PropertyDescriptor | undefined;
let savedSize: string | null;

async function flush(): Promise<void> {
  await act(async () => { for (let turn = 0; turn < 12; turn += 1) await Promise.resolve(); });
}

async function respond(read: PendingRead, payload: unknown, status = 200): Promise<void> {
  await act(async () => { read.resolve(new Response(JSON.stringify(payload), { status })); });
  await flush();
}

function profileReads(): PendingRead[] {
  return reads.filter(read => read.url.endsWith('/profile'));
}

function graphReads(): PendingRead[] {
  return reads.filter(read => read.url.includes('/memory-graph'));
}

async function mountHealth(): Promise<void> {
  render(<AgentProfilePanel />);
  expect(profileReads()).toHaveLength(1);
  await respond(profileReads()[0], profile());
  fireEvent.click(screen.getByRole('button', { name: 'Health' }));
  expect(profileReads()).toHaveLength(2);
  await respond(profileReads()[1], profile());
  expect(screen.getByText('196 episodes')).toBeVisible();
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(BASE_TIME);
  visibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  savedSize = localStorage.getItem('hxi_profile_panel_size');
  reads = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (url === '/api/config/avatars-enabled') return Promise.resolve(new Response('{"enabled":true}'));
    if (url.endsWith('/profile') || url.includes('/memory-graph') || init?.method === 'POST' || init?.method === 'PUT') {
      return new Promise<Response>((resolve, reject) => reads.push({ url, signal: init?.signal, resolve, reject }));
    }
    throw new Error(`Unexpected request: ${url}`);
  }));
  useStore.setState({ ...INITIAL, agents: new Map([['alpha', agent('alpha')], ['beta', agent('beta')]]),
    activeProfileAgent: 'alpha', activeProfileThreadId: null, chatThreads: new Map(), agentConversations: new Map(),
    connected: true, liveGeneration: 'generation-one', liveRepairEpoch: 0, notificationNavigation: null,
    showIntro: false, refreshWardRoomDmChannels: vi.fn() });
});

afterEach(() => {
  cleanup();
  useStore.setState(INITIAL, true);
  if (visibility) Object.defineProperty(document, 'visibilityState', visibility);
  else Reflect.deleteProperty(document, 'visibilityState');
  if (savedSize === null) localStorage.removeItem('hxi_profile_panel_size');
  else localStorage.setItem('hxi_profile_panel_size', savedSize);
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('issue 1370 profile ownership and measurements', () => {
  it('reads an initially disconnected profile over HTTP and permits manual recovery without polling', async () => {
    useStore.setState({ connected: false, liveGeneration: null });
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    await respond(profileReads()[0], profile());
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    expect(screen.getByText('196 episodes')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(1);
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    expect(profileReads()).toHaveLength(2);
    await respond(profileReads()[1], profile('alpha', 197));
    expect(screen.getByText('197 episodes')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
  });

  it('reads the Chat header once and starts polling only when a measured view is active', async () => {
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    await respond(profileReads()[0], profile());
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    expect(profileReads()).toHaveLength(2);
    await respond(profileReads()[1], profile());
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(profileReads()).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    expect(profileReads()[2].signal?.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(3);
  });

  it('refreshes Chat explicitly while hidden without starting automatic reads on visibility or connection loss', async () => {
    render(<AgentProfilePanel />);
    await respond(profileReads()[0], profile());
    act(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
      useStore.setState({ connected: false });
    });
    expect(profileReads()).toHaveLength(1);
    act(() => window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: 'alpha' } })));
    expect(profileReads()).toHaveLength(2);
    await respond(profileReads()[1], profile('alpha', 198));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(profileReads()).toHaveLength(2);
    act(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
      document.dispatchEvent(new Event('visibilitychange'));
      useStore.setState({ connected: true });
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(2);
  });

  it('polls the effective Profile fallback for a noncrew agent', async () => {
    render(<AgentProfilePanel />);
    await respond(profileReads()[0], { ...profile(), isCrew: false });
    expect(screen.queryByRole('button', { name: 'Chat' })).toBeNull();
    expect(screen.getByText('Identity')).toBeVisible();
    expect(profileReads()).toHaveLength(2);
    await respond(profileReads()[1], { ...profile(), isCrew: false });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(profileReads()).toHaveLength(3);
  });

  it('starts and stops Chat profile polling with the rendered avatar consumer', async () => {
    render(<AgentProfilePanel />);
    await respond(profileReads()[0], profile());
    fireEvent.click(screen.getByLabelText('Show avatar'));
    expect(profileReads()).toHaveLength(2);
    await respond(profileReads()[1], profile());
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(profileReads()).toHaveLength(3);
    fireEvent.click(screen.getByLabelText('Hide avatar'));
    expect(profileReads()[2].signal?.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(3);
  });

  it.each(['Work', 'Service', 'Self-image'])('suspends the profile poll on the %s tab', async tab => {
    await mountHealth();
    fireEvent.click(screen.getByRole('button', { name: tab }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Profile' }));
    expect(profileReads()).toHaveLength(3);
  });

  it('renders backend-verified profile and distinct graph populations through actual HTTP reads', async () => {
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    await respond(profileReads()[0], telemetryFixture.profile);
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    await respond(profileReads()[1], telemetryFixture.profile);
    expect(screen.getByText(`${telemetryFixture.selfQuery.domains.memory.episode_count} episodes`)).toBeVisible();
    expect(screen.getByText('11m')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Memory' }));
    expect(graphReads()).toHaveLength(1);
    await respond(graphReads()[0], telemetryFixture.memoryGraph);
    expect(screen.getByText('Displayed bounded agent sample: 3 episodes; 0 edges')).toBeVisible();
    expect(screen.getByText('Selected-agent stored membership: 4 episodes')).toBeVisible();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Ship-wide' }));
    await respond(graphReads()[1], telemetryFixture.shipGraph);
    expect(screen.getByText('Displayed bounded registered-crew sample: 4 episodes; 0 edges')).toBeVisible();
    expect(screen.getByTestId('graph-nodes')).toHaveTextContent('Beta observation');
  });

  it('fetches on mount and polls ten seconds after completion, retaining the producer sample', async () => {
    await mountHealth();
    const firstSample = profile().memoryCountMetadata!.sampleCompletedAt!;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(profileReads()).toHaveLength(3);
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
    expect(screen.getByRole('status')).toHaveTextContent(firstSample);
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    await respond(profileReads()[2], profile('alpha', 197));
    expect(screen.getByText('197 episodes')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Current.');
    await act(async () => { await vi.advanceTimersByTimeAsync(9_999); });
    expect(profileReads()).toHaveLength(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(profileReads()).toHaveLength(4);
  });

  it('fences same-agent supersession after a delayed body parse', async () => {
    await mountHealth();
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    let resolveBody!: (payload: unknown) => void;
    const json = vi.fn(() => new Promise<unknown>(resolve => { resolveBody = resolve; }));
    const response = new Response('{}');
    response.json = json;
    await act(async () => { profileReads()[2].resolve(response); });
    expect(json).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    expect(profileReads()[2].signal?.aborted).toBe(true);
    await respond(profileReads()[3], profile('alpha', 222));
    await act(async () => { resolveBody(profile('alpha', 999)); });
    await flush();
    expect(screen.getByText('222 episodes')).toBeVisible();
    expect(screen.queryByText('999 episodes')).toBeNull();
  });

  it('ignores superseded failures and pre-fetch completions across A-B-A', async () => {
    await mountHealth();
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    const oldAlpha = profileReads()[2];
    act(() => useStore.setState({ activeProfileAgent: 'beta' }));
    expect(profileReads()).toHaveLength(4);
    const oldBeta = profileReads()[3];
    expect(screen.queryByText('196 episodes')).toBeNull();
    act(() => useStore.setState({ activeProfileAgent: 'alpha' }));
    expect(profileReads()).toHaveLength(5);
    await respond(profileReads()[4], profile('alpha', 333));
    await respond(oldAlpha, profile('alpha', 999));
    await act(async () => { oldBeta.reject(new Error('Late failure')); });
    await flush();
    expect(screen.getByText('333 episodes')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Current.');
  });

  it('times out at fifteen seconds and stops automatic retries after the bounded budget', async () => {
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    expect(profileReads()).toHaveLength(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(profileReads()[1].signal?.aborted).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent('Unavailable.');
    expect(screen.queryByText('92%')).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(profileReads()).toHaveLength(3);
    await respond(profileReads()[2], {}, 503);
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(profileReads()).toHaveLength(4);
    await respond(profileReads()[3], {}, 500);
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(profileReads()).toHaveLength(4);
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    expect(profileReads()).toHaveLength(5);
  });

  it('suspends hidden and disconnected resources and refreshes on return, reconnect and resync', async () => {
    await mountHealth();
    const originalSample = profile().memoryCountMetadata!.sampleCompletedAt!;
    act(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(profileReads()).toHaveLength(2);
    act(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(profileReads()).toHaveLength(3);
    act(() => useStore.setState({ connected: false }));
    expect(profileReads()[2].signal?.aborted).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent(originalSample);
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(profileReads()).toHaveLength(3);
    act(() => useStore.setState({ connected: true }));
    expect(profileReads()).toHaveLength(4);
    act(() => useStore.setState({ liveRepairEpoch: 1 }));
    expect(profileReads()).toHaveLength(5);
    expect(profileReads()[3].signal?.aborted).toBe(true);
    act(() => useStore.setState({ liveGeneration: 'generation-two' }));
    expect(profileReads()).toHaveLength(6);
    await respond(profileReads()[5], profile('alpha', 444));
    await respond(profileReads()[4], profile('alpha', 888));
    expect(screen.getByText('444 episodes')).toBeVisible();
  });

  it.each(['close', 'unmount'])('aborts and stops timers on %s', async operation => {
    await mountHealth();
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    const pending = profileReads()[2];
    if (operation === 'close') fireEvent.click(screen.getByTitle('Close', { exact: true }));
    else cleanup();
    expect(pending.signal?.aborted).toBe(true);
    await respond(pending, profile('alpha', 999));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(profileReads()).toHaveLength(3);
    expect(screen.queryByText('999 episodes')).toBeNull();
  });

  it.each([0, null])('renders a measured %s without fabricating a count', async count => {
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    await respond(profileReads()[0], profile('alpha', count));
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    await respond(profileReads()[1], profile('alpha', count));
    expect(screen.getByText('Stored agent-membership episodes')).toBeVisible();
    expect(screen.getByText(count === null ? 'Unknown' : '0 episodes')).toBeVisible();
    expect(screen.getByText('System runtime uptime')).toBeVisible();
  });

  it('keeps legacy success consumable with unverified scope and time on Profile and Health', async () => {
    const legacy = profile();
    delete legacy.memoryCountMetadata;
    delete legacy.uptimeMetadata;
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    await respond(profileReads()[0], legacy);
    fireEvent.click(screen.getByRole('button', { name: 'Profile' }));
    await respond(profileReads()[1], legacy);
    expect(screen.getByText('Stale. Sample time/scope unverified.')).toBeVisible();
    expect(screen.getByText('Identity')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    await respond(profileReads()[2], legacy);
    expect(screen.getByText('196 episodes')).toBeVisible();
    expect(screen.getByRole('status')).not.toHaveTextContent('Current.');
  });

  it.each([
    ['wrong identity', (value: Record<string, unknown>): void => { value.id = 'beta'; }],
    ['string count', (value: Record<string, unknown>): void => { value.memoryCount = '196'; }],
    ['negative count', (value: Record<string, unknown>): void => { value.memoryCount = -1; }],
    ['fractional count', (value: Record<string, unknown>): void => { value.memoryCount = 1.2; }],
    ['wrong metadata subject', (value: Record<string, unknown>): void => { (value.memoryCountMetadata as Record<string, unknown>).subjectId = 'sovereign-beta'; }],
    ['wrong unit', (value: Record<string, unknown>): void => { (value.memoryCountMetadata as Record<string, unknown>).unit = 'seconds'; }],
    ['invalid timestamp', (value: Record<string, unknown>): void => { (value.memoryCountMetadata as Record<string, unknown>).sampleCompletedAt = 'yesterday'; }],
    ['unknown metadata key', (value: Record<string, unknown>): void => { (value.memoryCountMetadata as Record<string, unknown>).extra = true; }],
    ['null metadata', (value: Record<string, unknown>): void => { value.memoryCountMetadata = null; }],
  ])('rejects %s while retaining the last measured value as stale', async (_label, corrupt) => {
    await mountHealth();
    const value = profile('alpha', 999) as unknown as Record<string, unknown>;
    corrupt(value);
    fireEvent.click(screen.getByLabelText('Refresh profile'));
    await respond(profileReads()[2], value);
    expect(screen.getByText('196 episodes')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
    expect(screen.getByRole('status')).toHaveTextContent('Request failed.');
  });

  it('rejects nonfinite JSON-parser output and malformed bodies without store fallback', async () => {
    render(<AgentProfilePanel />);
    expect(profileReads()).toHaveLength(1);
    const response = new Response('{}');
    response.json = async (): Promise<unknown> => ({ ...profile(), uptime: Number.POSITIVE_INFINITY });
    await act(async () => { profileReads()[0].resolve(response); });
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    await act(async () => { profileReads()[1].resolve(new Response('not-json')); });
    await flush();
    expect(screen.getByRole('status')).toHaveTextContent('Request failed.');
    expect(screen.queryByText('92%')).toBeNull();
  });

  it('refreshes through the owner after vision mutation while a poll is pending', async () => {
    await mountHealth();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    const oldPoll = profileReads()[2];
    fireEvent.click(screen.getByTestId('vision-toggle'));
    const mutation = reads.find(read => read.url.endsWith('/vision-capability/set'))!;
    expect(mutation).toBeDefined();
    await respond(mutation, {});
    expect(profileReads()).toHaveLength(4);
    expect(oldPoll.signal?.aborted).toBe(true);
    await respond(profileReads()[3], { ...profile('alpha', 200), visionCapable: true });
    await respond(oldPoll, profile('alpha', 999));
    expect(screen.getByLabelText('Disable ambient vision')).toBeVisible();
    expect(screen.getByText('200 episodes')).toBeVisible();
  });

  it('suppresses closed group profiles and fences an old host mutation after a participant switch', async () => {
    useStore.setState({ activeProfileThreadId: 'group', chatThreads: new Map([['group', {
      id: 'group', title: 'Group', participants: ['captain', 'alpha', 'beta'], metadata: {}, created_at: 0, last_active_at: 0,
    }]]) });
    render(<AgentProfilePanel />);
    await flush();
    expect(screen.getByTestId('group-surface-title')).toBeVisible();
    expect(profileReads()).toHaveLength(0);
    fireEvent.click(screen.getByLabelText('Show avatar'));
    expect(profileReads()).toHaveLength(1);
    await respond(profileReads()[0], profile());
    fireEvent.click(screen.getByText('Approve alpha'));
    const mutation = reads.find(read => read.url.endsWith('/appearance'))!;
    expect(mutation).toBeDefined();
    act(() => useStore.setState({ activeProfileThreadId: null, activeProfileAgent: 'beta' }));
    expect(profileReads()).toHaveLength(2);
    await respond(mutation, {});
    expect(profileReads()).toHaveLength(2);
    await respond(profileReads()[1], profile('beta', 17));
    fireEvent.click(screen.getByRole('button', { name: 'Health' }));
    await respond(profileReads()[2], profile('beta', 17));
    expect(screen.getByText('17 episodes')).toBeVisible();
  });
});

describe('issue 1370 bounded graph scope', () => {
  it('renders the backend-verified failed-total payload without a parent profile subject', async () => {
    render(<ProfileMemoryTab agentId="alpha" />);
    expect(graphReads()).toHaveLength(1);
    const canonical = telemetryFixture.memoryGraph;
    const payload = { ...canonical, meta: { ...canonical.meta, total_episodes: null,
      total_measurement: { ...canonical.meta.total_measurement, status: 'failed',
        sample_started_at: null, sample_completed_at: null } } };
    await respond(graphReads()[0], payload);
    expect(screen.getByTestId('graph-nodes')).toHaveTextContent('Alpha observation');
    expect(screen.getByText('Selected-agent stored membership: Unknown episodes')).toBeVisible();
    expect(screen.getByText('Displayed bounded agent sample: 3 episodes; 0 edges')).toBeVisible();
    expect(screen.getByRole('status')).not.toHaveTextContent('Request failed.');
  });

  it('reads and manually refreshes disconnected Memory over HTTP without automatic polling', async () => {
    useStore.setState({ connected: false, liveGeneration: null });
    render(<ProfileMemoryTab agentId="alpha" subjectId="sovereign-alpha" />);
    expect(screen.getByLabelText('Refresh memory graph')).toBeEnabled();
    expect(graphReads()).toHaveLength(1);
    await respond(graphReads()[0], graph());
    expect(screen.getByTestId('graph-nodes')).toHaveTextContent('Own episode');
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(graphReads()).toHaveLength(1);
    fireEvent.click(screen.getByLabelText('Refresh memory graph'));
    expect(graphReads()).toHaveLength(2);
    await respond(graphReads()[1], graph(false, true));
    expect(screen.getByText('No episodes in this bounded selection.')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
  });

  it('distinguishes selected-agent storage from the ship sample and fences scope responses', async () => {
    render(<ProfileMemoryTab agentId="alpha" subjectId="sovereign-alpha" />);
    expect(graphReads()).toHaveLength(1);
    await respond(graphReads()[0], graph());
    expect(screen.getByTestId('graph-nodes')).toHaveTextContent('Own episode');
    fireEvent.click(screen.getByLabelText('Refresh memory graph'));
    const oldScope = graphReads()[1];
    fireEvent.click(screen.getByRole('checkbox', { name: 'Ship-wide' }));
    expect(graphReads()).toHaveLength(3);
    expect(oldScope.signal?.aborted).toBe(true);
    await respond(graphReads()[2], graph(true));
    await respond(oldScope, graph());
    expect(screen.getByText('Displayed bounded registered-crew sample: 1 episodes; 0 edges')).toBeVisible();
    expect(screen.getByText('Selected-agent stored membership: 196 episodes')).toBeVisible();
    expect(screen.getByTestId('graph-nodes')).toHaveTextContent('Other agent episode');
    expect(screen.queryByText(/Showing .* of/)).toBeNull();
  });

  it('retains a nonzero total on empty selection and reports unknown separately from zero', async () => {
    render(<ProfileMemoryTab agentId="alpha" subjectId="sovereign-alpha" />);
    expect(graphReads()).toHaveLength(1);
    await respond(graphReads()[0], graph(false, true));
    expect(screen.getByText('No episodes in this bounded selection.')).toBeVisible();
    expect(screen.getByText('Selected-agent stored membership: 196 episodes')).toBeVisible();
    const unknown = graph(false, true);
    unknown.meta.total_episodes = null;
    unknown.meta.total_measurement!.status = 'failed';
    fireEvent.click(screen.getByLabelText('Refresh memory graph'));
    await respond(graphReads()[1], unknown);
    expect(screen.getByText('Selected-agent stored membership: Unknown episodes')).toBeVisible();
  });

  it.each(['selection', 'count', 'subject'])('rejects malformed graph %s and retains stale selection', async kind => {
    render(<ProfileMemoryTab agentId="alpha" subjectId="sovereign-alpha" />);
    expect(graphReads()).toHaveLength(1);
    await respond(graphReads()[0], graph());
    const invalid = graph();
    if (kind === 'selection') invalid.meta.selection!.population = 'registered_crew_bounded_graph';
    if (kind === 'count') invalid.meta.nodes_shown = 0;
    if (kind === 'subject') invalid.meta.total_measurement!.subject_id = 'sovereign-beta';
    fireEvent.click(screen.getByLabelText('Refresh memory graph'));
    await respond(graphReads()[1], invalid);
    expect(screen.getByRole('status')).toHaveTextContent('Stale.');
    expect(screen.getByTestId('graph-nodes')).toHaveTextContent('Own episode');
  });

  it('keeps legacy graph data unverified and handles unavailable selection without empty-success claims', async () => {
    render(<ProfileMemoryTab agentId="alpha" />);
    expect(graphReads()).toHaveLength(1);
    await respond(graphReads()[0], {}, 503);
    expect(screen.getByRole('status')).toHaveTextContent('Unavailable.');
    expect(screen.queryByText('No episodes in this bounded selection.')).toBeNull();
    const legacy = graph();
    delete legacy.meta.selection;
    delete legacy.meta.total_measurement;
    fireEvent.click(screen.getByLabelText('Refresh memory graph'));
    await respond(graphReads()[1], legacy);
    expect(screen.getByRole('status')).toHaveTextContent('Sample time/scope unverified.');
  });
});

describe('issue 1370 registered population', () => {
  it('requires connected established state, accepts zero, updates and invalidates on disconnect/reset', () => {
    useStore.setState({ showIntro: true, connected: false, liveGeneration: null });
    render(<WelcomeOverlay />);
    expect(screen.getByText('Registered agents: unavailable')).toBeVisible();
    act(() => useStore.setState({ connected: true }));
    expect(screen.getByText('Registered agents: unavailable')).toBeVisible();
    act(() => useStore.setState({ liveGeneration: 'established' }));
    expect(screen.getByText('Registered agents: 2')).toBeVisible();
    act(() => useStore.setState({ agents: new Map() }));
    expect(screen.getByText('Registered agents: 0')).toBeVisible();
    act(() => useStore.setState({ agents: new Map([['alpha', agent('alpha')]]) }));
    expect(screen.getByText('Registered agents: 1')).toBeVisible();
    act(() => useStore.setState({ connected: false }));
    expect(screen.getByText('Registered agents: unavailable')).toBeVisible();
    act(() => useStore.setState({ connected: true, liveGeneration: 'restart' }));
    expect(screen.getByText('Registered agents: 1')).toBeVisible();
    act(() => useStore.setState({ liveGeneration: null }));
    expect(screen.getByText('Registered agents: unavailable')).toBeVisible();
    expect(screen.queryByText(/input box above/)).toBeNull();
  });
});