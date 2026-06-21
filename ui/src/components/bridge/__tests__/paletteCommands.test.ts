// AD-946: pure-helper tests for the command-palette flattening + matching.
// Imports the REAL buildBridgeStations (no mocks) so the command list stays
// pinned to the single source of truth (BF-287 — no over-mock at the boundary).
import { describe, it, expect, afterEach, vi } from 'vitest';
import { buildBridgeStations } from '../stations';
import { buildPaletteCommands, matchPaletteCommands } from '../paletteCommands';
import { useStore } from '../../../store/useStore';

afterEach(() => {
  vi.restoreAllMocks();
});

const STATIONS = () => buildBridgeStations({ dmChannelCount: 4, kanbanCount: 7, totalUnread: 3 });

describe('AD-946 buildPaletteCommands — flatten the station registry', () => {
  it('returns the 16 Captain-facing launches with the expected labels', () => {
    const cmds = buildPaletteCommands(STATIONS());
    expect(cmds.length).toBe(16);
    expect(cmds.map((c) => c.label)).toEqual([
      'Ward Room', 'Chats', 'Crew', 'Personnel', 'Metrics',
      'Notebooks', 'Records', 'Explorer', 'Work Board', 'System', "Ship's Locker", 'MCP Servers', 'MCP Apps', 'Workstation', 'Browser', 'Settings',
    ]);
  });

  it('Communications contributes its ACTIONS (Ward Room + Chats), never a communications:expand', () => {
    const cmds = buildPaletteCommands(STATIONS());
    const comms = cmds.filter((c) => c.station === 'Communications');
    expect(comms.map((c) => c.label)).toEqual(['Ward Room', 'Chats']);
    // The onExpand is skipped because the station has actions → no duplicate Ward Room.
    expect(cmds.some((c) => c.id === 'communications:expand')).toBe(false);
    expect(cmds.filter((c) => c.label === 'Ward Room').length).toBe(1);
  });

  it('body-only stations surface their onExpand launch with the onExpandLabel', () => {
    const cmds = buildPaletteCommands(STATIONS());
    const ops = cmds.filter((c) => c.id === 'operations:expand');
    expect(ops.length).toBe(1);
    expect(ops[0].label).toBe('Work Board');
    expect(ops[0].station).toBe('Operations');

    // AD-1001b: Engineering is now action-bearing (System mirror + Ship's
    // Locker), so it surfaces ACTIONS, not an engineering:expand fallback
    // (same treatment as Communications). System is preserved via the mirror
    // action; the Ship's Locker is the new launch. AD-1018 adds MCP Servers;
    // AD-1021 adds Workstation; AD-1024 adds MCP Apps; AD-1052 adds Browser.
    expect(cmds.some((c) => c.id === 'engineering:expand')).toBe(false);
    const eng = cmds.filter((c) => c.station === 'Engineering');
    expect(eng.map((c) => c.label)).toEqual(['System', "Ship's Locker", 'MCP Servers', 'MCP Apps', 'Workstation', 'Browser']);
    expect(eng.find((c) => c.label === 'System')).toBeTruthy();
  });

  it('excludes config panels (forward marker AD-946a)', () => {
    const cmds = buildPaletteCommands(STATIONS());
    // The engineering Environment config + the comms-admin config must NOT appear.
    expect(cmds.some((c) => c.label === 'Environment')).toBe(false);
    expect(cmds.some((c) => c.label === 'Communications')).toBe(false);
  });

  it("the Work Board launch's .run() fires the same store action the Bridge fires", () => {
    const setState = vi.spyOn(useStore, 'setState');
    const cmds = buildPaletteCommands(STATIONS());
    const workBoard = cmds.find((c) => c.label === 'Work Board')!;
    workBoard.run();
    expect(setState).toHaveBeenCalledWith({ mainViewer: 'work' });
  });
});

describe('AD-946 matchPaletteCommands — case-insensitive token-AND substring', () => {
  const cmds = buildPaletteCommands(STATIONS());

  it('single-term matches resolve the right launch', () => {
    expect(matchPaletteCommands('work', cmds).map((c) => c.label)).toEqual(['Work Board', 'Workstation']);
    expect(matchPaletteCommands('ward', cmds).map((c) => c.label)).toEqual(['Ward Room']);
    expect(matchPaletteCommands('settings', cmds).map((c) => c.label)).toEqual(['Settings']);
    expect(matchPaletteCommands('chats', cmds).map((c) => c.label)).toEqual(['Chats']);
  });

  it('multi-term matches AND across the `${station} ${label}` haystack', () => {
    expect(matchPaletteCommands('science records', cmds).map((c) => c.label)).toEqual(['Records']);
  });

  it('AD-946b: empty / whitespace-only query lists ALL commands (a bare ">" shows everything)', () => {
    expect(matchPaletteCommands('', cmds)).toEqual(cmds);
    expect(matchPaletteCommands('   ', cmds)).toEqual(cmds);
    // a fresh array, never the caller's own reference
    expect(matchPaletteCommands('', cmds)).not.toBe(cmds);
  });

  it('a non-matching query returns []', () => {
    expect(matchPaletteCommands('xyzzy', cmds)).toEqual([]);
  });

  it('matching is case-insensitive', () => {
    expect(matchPaletteCommands('WARD', cmds).map((c) => c.label)).toEqual(['Ward Room']);
  });
});
