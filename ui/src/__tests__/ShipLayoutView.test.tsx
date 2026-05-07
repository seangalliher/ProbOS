/**
 * AD-520: ShipLayoutView tests.
 *
 * Mocks @react-three/fiber + @react-three/drei to render plain DOM stand-ins.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="mock-r3f-canvas">{children}</div>,
  useFrame: () => {},
}));
vi.mock('@react-three/drei', () => ({
  OrbitControls: () => <div data-testid="mock-orbit-controls" />,
  Text: ({ children, color }: any) => (
    <div data-testid="mock-text" data-color={color}>{children}</div>
  ),
}));

import ShipLayoutView, { computePlacements, alertTint } from '../components/spatial/ShipLayoutView';
import { useStore } from '../store/useStore';

const SAMPLE_LAYOUT = {
  schema_version: 1,
  decks: [
    { deck_id: 'bridge', name: 'Bridge', department_id: 'command', position: [0, 6, 0] as [number, number, number], dimensions: [8, 1.5, 6] as [number, number, number], accent_color: '#f0b060', post_offsets: { captain: [0, 0, -1] as [number, number, number] } },
    { deck_id: 'engineering', name: 'Engineering', department_id: 'engineering', position: [0, 0, 6] as [number, number, number], dimensions: [8, 2, 6] as [number, number, number], accent_color: '#d8742a', post_offsets: { chief_engineer: [0, 0, 0] as [number, number, number] } },
    { deck_id: 'sickbay', name: 'Sickbay', department_id: 'medical', position: [-6, 3, 0] as [number, number, number], dimensions: [6, 1.5, 6] as [number, number, number], accent_color: '#54c474', post_offsets: {} },
    { deck_id: 'tactical', name: 'Tactical', department_id: 'security', position: [6, 3, 0] as [number, number, number], dimensions: [6, 1.5, 6] as [number, number, number], accent_color: '#c84858', post_offsets: {} },
    { deck_id: 'science_lab', name: 'Science Lab', department_id: 'science', position: [0, 3, -6] as [number, number, number], dimensions: [6, 1.5, 6] as [number, number, number], accent_color: '#5ca0d4', post_offsets: {} },
    { deck_id: 'computer_core', name: 'Computer Core', department_id: 'ship-systems', position: [0, -3, 0] as [number, number, number], dimensions: [6, 2, 6] as [number, number, number], accent_color: '#8870c4', post_offsets: {} },
    { deck_id: 'common_areas', name: 'Common Areas', department_id: null, position: [0, 1, 0] as [number, number, number], dimensions: [10, 1, 10] as [number, number, number], accent_color: '#666680', post_offsets: {} },
  ],
};

function reset() {
  useStore.setState({
    spatialLayoutData: null,
    spatialGraphData: null,
    spatialSelectedNode: null,
    agents: new Map(),
  });
}

describe('ShipLayoutView (AD-520)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); reset(); });

  it('renders R3F Canvas with deck label texts when layout has 6+ decks', () => {
    useStore.setState({
      spatialLayoutData: SAMPLE_LAYOUT as any,
      spatialGraphData: { nodes: [], edges: [], generated_at: 0 },
    });
    render(<ShipLayoutView />);
    expect(screen.getByTestId('mock-r3f-canvas')).toBeTruthy();
    const labels = screen.getAllByTestId('mock-text');
    expect(labels.length).toBe(7);
    const labelTexts = labels.map(l => l.textContent);
    expect(labelTexts).toContain('Bridge');
    expect(labelTexts).toContain('Engineering');
  });

  it('computePlacements positions one mesh per agent at deck_position + post_offset', () => {
    const placements = computePlacements(
      SAMPLE_LAYOUT as any,
      [
        { id: 'cap', type: 'agent', department: 'command', post: 'captain', on_watch: true },
        { id: 'eng', type: 'agent', department: 'engineering', post: 'chief_engineer', on_watch: true },
      ],
      new Map(),
    );
    expect(placements).toHaveLength(2);
    const cap = placements.find(p => p.agent_id === 'cap')!;
    expect(cap.position).toEqual([0, 6, -1]);
    expect(cap.deck_id).toBe('bridge');
  });

  it('CRITICAL alert level produces red tint via alertTint helper', () => {
    expect(alertTint('CRITICAL')).toBe('#c84858');
  });

  it('ALERT alert level produces amber tint via alertTint helper', () => {
    expect(alertTint('ALERT')).toBe('#f0b060');
  });

  it('CRITICAL alert tints deck label color', () => {
    useStore.setState({
      spatialLayoutData: SAMPLE_LAYOUT as any,
      spatialGraphData: { nodes: [], edges: [], generated_at: 0 },
    });
    render(<ShipLayoutView alertLevel="CRITICAL" />);
    const labels = screen.getAllByTestId('mock-text');
    // All deck labels should be tinted red
    for (const l of labels) {
      expect(l.getAttribute('data-color')).toBe('#c84858');
    }
  });

  it('agent without known department falls back to common_areas deck', () => {
    const placements = computePlacements(
      SAMPLE_LAYOUT as any,
      [{ id: 'drift', type: 'agent', department: 'no-such', post: '', on_watch: true }],
      new Map(),
    );
    expect(placements[0].deck_id).toBe('common_areas');
    expect(placements[0].on_watch).toBe(false);
  });

  it('shows "No spatial layout" status when spatialLayoutData is null', () => {
    useStore.setState({ spatialLayoutData: null });
    render(<ShipLayoutView />);
    expect(screen.getByTestId('ship-layout-empty')).toBeTruthy();
  });

  it('non-agent nodes are excluded from placements', () => {
    const placements = computePlacements(
      SAMPLE_LAYOUT as any,
      [
        { id: 'science', type: 'department', department: null, post: '' },
        { id: 'cap', type: 'agent', department: 'command', post: 'captain' },
      ],
      new Map(),
    );
    expect(placements).toHaveLength(1);
    expect(placements[0].agent_id).toBe('cap');
  });
});
