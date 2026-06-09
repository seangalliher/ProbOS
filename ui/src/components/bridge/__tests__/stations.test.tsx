// AD-943: tests for the Command-Station model + registry and the BridgePanel
// migration. The model cases are pure (no render); the panel case seeds the
// REAL store via useStore.setState (BF-287 — no MagicMock/over-mock at the
// boundary), mirroring ChatsPanel.drag.test.tsx, and stubs global.fetch to a
// resolved empty JSON so the on-mount refreshDms honest-degrades in jsdom.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
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
    const stations = buildBridgeStations({ dmChannelCount: 4, kanbanCount: 7 });
    expect(stations.map(s => s.id)).toEqual(STATION_ORDER);

    const comms = stations.find(s => s.id === 'communications')!;
    expect(comms.count).toBe(4);
    expect(typeof comms.onExpand).toBe('function');
    expect(comms.body).toBeTruthy();
    expect(comms.config.map(c => c.id)).toContain('comms-admin');

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

  it('personnel/science/command are empty modelled placeholders (not populated)', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0 });
    for (const id of ['personnel', 'science', 'command'] as const) {
      const st = stations.find(s => s.id === id)!;
      expect(st.actions).toEqual([]);
      expect(st.config).toEqual([]);
      expect(st.body).toBeUndefined();
      expect(isPopulated(st)).toBe(false);
    }
  });

  it('the descriptor can HOLD a future launch (AD-944 shape) and invoke it', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0 });
    const personnel = stations.find(s => s.id === 'personnel')!;
    let fired = false;
    const action: StationAction = {
      id: 'open-crew',
      label: 'Crew Manifest',
      onInvoke: () => { fired = true; },
    };
    personnel.actions.push(action);
    // an action makes the placeholder populated, and the slot is callable
    expect(isPopulated(personnel)).toBe(true);
    personnel.actions[0].onInvoke();
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
