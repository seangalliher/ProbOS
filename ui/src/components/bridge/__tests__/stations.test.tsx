// AD-943: tests for the Command-Station model + registry and the BridgePanel
// migration. The model cases are pure (no render); the panel case seeds the
// REAL store via useStore.setState (BF-287 — no MagicMock/over-mock at the
// boundary), mirroring ChatsPanel.drag.test.tsx, and stubs global.fetch to a
// resolved empty JSON so the on-mount refreshDms honest-degrades in jsdom.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import {
  STATION_ORDER,
  STATION_META,
  buildBridgeStations,
  isPopulated,
  type StationAction,
} from '../stations';
import { BridgePanel } from '../../BridgePanel';
import { useStore } from '../../../store/useStore';

// HXI #3 — stroke-SVG glyphs only, never emoji.
const EMOJI = /\p{Extended_Pictographic}/u;

afterEach(() => {
  cleanup();
  // Restore the seeded slices to their store defaults so tests stay isolated.
  useStore.setState({
    wardRoomDmChannels: [],
    missionControlTasks: null,
    agentTasks: null,
    notifications: null,
    wardRoomUnread: {},
    chatsOpen: false,
  });
  vi.unstubAllGlobals();
});

describe('AD-943 station taxonomy (STATION_ORDER / STATION_META)', () => {
  it('STATION_ORDER is the canonical 6-station order', () => {
    expect(STATION_ORDER).toEqual([
      'communications', 'personnel', 'science', 'operations', 'engineering', 'command',
    ]);
  });

  it('every station meta has a non-empty title, a 6-hex accent, and no emoji (HXI #3)', () => {
    for (const id of STATION_ORDER) {
      const meta = STATION_META[id];
      expect(meta.title.length).toBeGreaterThan(0);
      expect(meta.accent).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(meta.title).not.toMatch(EMOJI);
    }
  });
});

describe('AD-943 buildBridgeStations factory', () => {
  it('returns the 6 stations in canonical order with the migrated bodies/config', () => {
    const stations = buildBridgeStations({ dmChannelCount: 4, kanbanCount: 7, totalUnread: 3 });
    expect(stations.map(s => s.id)).toEqual(STATION_ORDER);

    const comms = stations.find(s => s.id === 'communications')!;
    expect(comms.count).toBe(4);
    expect(typeof comms.onExpand).toBe('function');
    expect(comms.body).toBeTruthy();
    expect(comms.config.map(c => c.id)).toContain('comms-admin');
    // AD-944: the two migrated communications launches; Ward Room carries totalUnread.
    expect(comms.actions.map(a => a.id)).toEqual(['ward-room-action', 'chats-toggle']);
    const wardRoom = comms.actions.find(a => a.id === 'ward-room-action')!;
    expect(wardRoom.count).toBe(3);

    const operations = stations.find(s => s.id === 'operations')!;
    expect(operations.count).toBe(7);
    expect(typeof operations.onExpand).toBe('function');
    expect(operations.body).toBeTruthy();

    const engineering = stations.find(s => s.id === 'engineering')!;
    expect(typeof engineering.onExpand).toBe('function');
    expect(engineering.body).toBeTruthy();

    // every station exposes actions[] and config[] as arrays
    for (const s of stations) {
      expect(Array.isArray(s.actions)).toBe(true);
      expect(Array.isArray(s.config)).toBe(true);
    }
  });

  it('AD-944: personnel/science/command are now populated with the migrated launches', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0, totalUnread: 0 });
    const ids = (id: string) =>
      stations.find(s => s.id === id)!.actions.map(a => a.id);
    expect(ids('personnel')).toEqual(['crew-action', 'personnel-toggle', 'behavioral-metrics-toggle']);
    expect(ids('science')).toEqual(['notebooks-toggle', 'knowledge-browser-toggle', 'spatial-explorer-toggle']);
    expect(ids('command')).toEqual(['topnav-settings']);
    for (const id of ['personnel', 'science', 'command'] as const) {
      expect(isPopulated(stations.find(s => s.id === id)!)).toBe(true);
    }
  });

  it('AD-946: operations/engineering carry an onExpandLabel; the others are undefined', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0, totalUnread: 0 });
    const byId = (id: string) => stations.find(s => s.id === id)!;
    expect(byId('operations').onExpandLabel).toBe('Work Board');
    expect(byId('engineering').onExpandLabel).toBe('System');
    for (const id of ['communications', 'personnel', 'science', 'command'] as const) {
      expect(byId(id).onExpandLabel).toBeUndefined();
    }
  });

  it('the descriptor can HOLD a future launch (AD-944 shape) and invoke it', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0, totalUnread: 0 });
    const personnel = stations.find(s => s.id === 'personnel')!;
    let fired = false;
    const action: StationAction = {
      id: 'open-crew',
      label: 'Crew Manifest',
      onInvoke: () => { fired = true; },
    };
    const before = personnel.actions.length;
    personnel.actions.push(action);
    expect(isPopulated(personnel)).toBe(true);
    personnel.actions[before].onInvoke();   // invoke the pushed action, not the migrated crew launch
    expect(fired).toBe(true);
  });
});

describe('AD-943 BridgePanel renders stations + activity feed (real store, BF-287)', () => {
  it('shows the 3 migrated stations, the activity feed, the Shutdown footer, no emoji', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    useStore.setState({
      wardRoomDmChannels: [],
      missionControlTasks: [],
      agentTasks: [],
      notifications: [
        {
          id: 'n1',
          agent_id: 'a1',
          agent_type: 'Sensors',
          department: 'general',
          notification_type: 'info',
          title: 'Diagnostic complete',
          detail: '',
          action_url: '',
          created_at: 0,
          acknowledged: false,
        },
      ],
    });

    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);
    // Flush the on-mount refreshDms fetch (resolves to []) within act.
    await screen.findByText(/SHUTDOWN/i);

    // the three migrated station headers (System→Engineering, Work Board→Operations)
    expect(screen.getByText(/Communications/i)).toBeTruthy();
    expect(screen.getByText(/Operations/i)).toBeTruthy();
    expect(screen.getByText(/Engineering/i)).toBeTruthy();

    // the command-station identity hooks exist (accent-edged data-station)
    expect(container.querySelector('[data-station="communications"]')).toBeTruthy();
    expect(container.querySelector('[data-station="engineering"]')).toBeTruthy();

    // the activity feed still renders (NOT a station — HXI #9)
    expect(screen.getByText(/Notifications/i)).toBeTruthy();

    // the Shutdown footer survives the migration
    expect(screen.getByText(/SHUTDOWN/i)).toBeTruthy();

    // HXI #3 — no emoji anywhere in the rendered surface
    expect(document.body.textContent || '').not.toMatch(EMOJI);
  });
});

describe('AD-944 BridgePanel renders the migrated toolbar launches as station rows (real store, BF-287)', () => {
  it('renders personnel/science/command stations, resolves the migrated launch testIds, flips a sync flag, no emoji', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    useStore.setState({
      wardRoomDmChannels: [],
      missionControlTasks: [],
      agentTasks: [],
      notifications: [],
      wardRoomUnread: {},
      chatsOpen: false,
    });

    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);
    // Flush the on-mount refreshDms fetch (resolves to []) within act.
    await screen.findByText(/SHUTDOWN/i);

    // the three placeholders AD-943 hid are now populated → they render
    expect(screen.getByText(/Personnel/i)).toBeTruthy();
    expect(screen.getByText(/Science/i)).toBeTruthy();
    expect(screen.getByText(/Command/i)).toBeTruthy();
    expect(container.querySelector('[data-station="personnel"]')).toBeTruthy();

    // BridgeSection renders children only when expanded — click each header first,
    // then the migrated launch testIds resolve on the station rows.
    fireEvent.click(screen.getByText(/Personnel/i));
    expect(screen.getByTestId('behavioral-metrics-toggle')).toBeTruthy();

    fireEvent.click(screen.getByText(/Science/i));
    expect(screen.getByTestId('spatial-explorer-toggle')).toBeTruthy();

    fireEvent.click(screen.getByText(/Command/i));
    expect(screen.getByTestId('topnav-settings')).toBeTruthy();

    // invoking a SYNC launch flips its store flag deterministically (no await)
    fireEvent.click(screen.getByText(/Communications/i));
    expect(screen.getByTestId('chats-toggle')).toBeTruthy();
    fireEvent.click(screen.getByTestId('chats-toggle'));
    expect(useStore.getState().chatsOpen).toBe(true);

    // HXI #3 — no emoji anywhere in the rendered surface
    expect(document.body.textContent || '').not.toMatch(EMOJI);
  });
});
