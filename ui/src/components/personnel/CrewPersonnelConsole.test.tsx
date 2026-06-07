/** AD-896 (Wave 254) vitest — Crew Personnel Console (Ship's Office).
 * Frontend-only window shell: roster master pane bound to GET /api/crew/roster,
 * selection loads the detail (service-record placeholder) pane, display-mode
 * toggle persistence, and the HXI no-emoji (stroke-SVG glyph) guard. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore, loadPersonnelLayout } from '../../store/useStore';
import CrewPersonnelConsole from './CrewPersonnelConsole';

const DEFAULT_RECT = { x: 120, y: 80, w: 880, h: 660 };

const ROSTER = {
  crew: [
    {
      agent_id: 'agent-data',
      agent_type: 'ScienceAgent',
      callsign: 'Data',
      post: 'Operations Officer',
      department: 'science',
      rank: 'commander',
      assigned: true,
      billet_state: 'billeted',
    },
    {
      agent_id: 'agent-worf',
      agent_type: 'SecurityAgent',
      callsign: 'Worf',
      post: 'Chief of Security',
      department: 'security',
      rank: 'lieutenant',
      assigned: true,
      billet_state: 'billeted',
    },
  ],
  count: 2,
};

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    personnelConsoleOpen: true,
    personnelDisplayMode: 'floating',
    personnelWindowRect: { ...DEFAULT_RECT },
  });
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: async () => ROSTER }) as any
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CrewPersonnelConsole (AD-896)', () => {
  it('1. renders the roster from GET /api/crew/roster', async () => {
    render(<CrewPersonnelConsole />);
    expect(global.fetch).toHaveBeenCalledWith('/api/crew/roster');
    expect(await screen.findByText('Data')).toBeTruthy();
    expect(screen.getByText('Worf')).toBeTruthy();
  });

  it('2. selecting an agent loads the record (detail) pane', async () => {
    render(<CrewPersonnelConsole />);
    fireEvent.click(await screen.findByTestId('personnel-roster-row-agent-data'));
    const pane = screen.getByTestId('personnel-record-pane');
    await waitFor(() => {
      expect(pane.textContent).toContain('Operations Officer');
    });
    // AD-897 fills the placeholder with the ServiceRecord detail view.
    expect(pane.querySelector('[data-testid="service-record"]')).toBeTruthy();
  });

  it('3. defaults to a floating window at the persisted/default rect', () => {
    render(<CrewPersonnelConsole />);
    const panel = screen.getByTestId('personnel-console');
    expect(panel.getAttribute('data-mode')).toBe('floating');
    expect(panel.style.left).toBe('120px');
    expect(panel.style.top).toBe('80px');
  });

  it('4. Dock switches to the docked sidebar; maximize control hidden when docked', () => {
    render(<CrewPersonnelConsole />);
    fireEvent.click(screen.getByLabelText('Dock Crew Personnel Console'));
    expect(screen.getByTestId('personnel-console').getAttribute('data-mode')).toBe('docked');
    expect(screen.queryByLabelText('Maximize Crew Personnel Console')).toBeNull();
  });

  it('5. mode toggle persists probos.personnel.mode to localStorage', () => {
    render(<CrewPersonnelConsole />);
    fireEvent.click(screen.getByLabelText('Dock Crew Personnel Console'));
    expect(localStorage.getItem('probos.personnel.mode')).toBe('docked');
  });

  it('6. loadPersonnelLayout rehydrates persisted rect; falls back on malformed JSON', () => {
    localStorage.setItem('probos.personnel.mode', 'docked');
    localStorage.setItem('probos.personnel.rect', JSON.stringify({ x: 5, y: 6, w: 700, h: 500 }));
    const ok = loadPersonnelLayout();
    expect(ok.mode).toBe('docked');
    expect(ok.rect).toEqual({ x: 5, y: 6, w: 700, h: 500 });

    localStorage.setItem('probos.personnel.rect', '{not valid json');
    const fallback = loadPersonnelLayout();
    expect(fallback.rect).toEqual(DEFAULT_RECT);
  });

  it('7. header controls render stroke-SVG glyphs, not emoji (HXI Principle #3)', () => {
    render(<CrewPersonnelConsole />);
    const dock = screen.getByLabelText('Dock Crew Personnel Console');
    expect(dock.querySelector('svg')).toBeTruthy();
    expect(/\p{Extended_Pictographic}/u.test(dock.textContent || '')).toBe(false);
  });

  it('8. degrades to an empty roster when the fetch fails', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: false, status: 500, json: async () => ({}) }) as any
    );
    render(<CrewPersonnelConsole />);
    expect(await screen.findByText('No crew aboard.')).toBeTruthy();
  });
});
