/** AD-905 vitest — ClinicalPanel.
 *
 * Deps-injected fetchImpl (no global stub). A URL-routing mock serves the
 * roster, clinical-streams, and notes endpoints. Verifies the picker renders,
 * selecting an agent renders all five stream cards + both sparklines + the zone
 * strip + the notes list, the write box POSTs the typed body, a server 403 swaps
 * to the access-denied state, the client placeholder renders WITHOUT any fetch,
 * empty notes degrade gracefully, HXI calls omit as_agent_id, and the no-emoji
 * guard holds.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';
import ClinicalPanel from './ClinicalPanel';

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F1E6}-\u{1F1FF}]/u;

const ROSTER = {
  crew: [{ agent_id: 'agent-data', callsign: 'Data', department: 'science' }],
};

const CLINICAL = {
  agent_id: 'agent-data',
  streams: {
    trust: {
      events: [
        { timestamp: 1, success: true, old_score: 0.5, new_score: 0.6, intent_type: 'x' },
        { timestamp: 2, success: true, old_score: 0.6, new_score: 0.7, intent_type: 'y' },
      ],
      raw: [3, 1],
    },
    zones: [
      { zone: 'green', timestamp: 1 },
      { zone: 'amber', timestamp: 2 },
    ],
    self_similarity: [
      { timestamp: 1, similarity: 0.9 },
      { timestamp: 2, similarity: 0.95 },
    ],
    hebbian_drift: { drift_trend: 0.12, assessments: [{}, {}] },
    duty: { execution_count: 5, last_executed: 1700000000, success_rate: 0.8 },
  },
};

const NOTES = {
  notes: [
    {
      id: 'n-1',
      target_agent_id: 'agent-data',
      author_agent_id: 'counselor',
      body: 'Stable mood',
      disclosure_level: 3,
      created_at: 1700000000,
    },
  ],
};

function res(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as Response;
}

interface Routes {
  roster?: unknown;
  clinical?: { body?: unknown; status?: number };
  notes?: { body?: unknown; status?: number };
  notePostId?: string;
}

function routedFetch(routes: Routes) {
  return vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes('/api/crew/roster')) {
      return Promise.resolve(res(routes.roster ?? { crew: [] }));
    }
    if (u.includes('/api/counselor/clinical/')) {
      const st = routes.clinical?.status ?? 200;
      return Promise.resolve(res(routes.clinical?.body ?? CLINICAL, st < 400, st));
    }
    if (u.includes('/api/counselor/notes/')) {
      if (init?.method === 'POST') {
        return Promise.resolve(res({ id: routes.notePostId ?? 'note-new' }));
      }
      const st = routes.notes?.status ?? 200;
      return Promise.resolve(res(routes.notes?.body ?? { notes: [] }, st < 400, st));
    }
    return Promise.resolve(res({}, false, 404));
  });
}

describe('ClinicalPanel (AD-905)', () => {
  afterEach(() => cleanup());

  it('renders_picker_and_empty_detail_before_selection', async () => {
    const fm = routedFetch({ roster: ROSTER });
    render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => {
      expect(screen.getByTestId('clinical-agent-row-agent-data')).toBeTruthy();
    });
    expect(screen.getByTestId('clinical-empty')).toBeTruthy();
  });

  it('select_agent_renders_all_five_streams_and_notes', async () => {
    const fm = routedFetch({ roster: ROSTER, clinical: { body: CLINICAL }, notes: { body: NOTES } });
    render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => screen.getByTestId('clinical-agent-row-agent-data'));
    fireEvent.click(screen.getByTestId('clinical-agent-row-agent-data'));

    await waitFor(() => {
      expect(screen.getByTestId('clinical-stream-trust')).toBeTruthy();
    });
    expect(screen.getByTestId('clinical-stream-zones')).toBeTruthy();
    expect(screen.getByTestId('clinical-stream-self_similarity')).toBeTruthy();
    expect(screen.getByTestId('clinical-stream-hebbian')).toBeTruthy();
    expect(screen.getByTestId('clinical-stream-duty')).toBeTruthy();
    expect(screen.getByTestId('clinical-sparkline-trust')).toBeTruthy();
    expect(screen.getByTestId('clinical-sparkline-self_similarity')).toBeTruthy();
    expect(screen.getByTestId('clinical-zonestrip')).toBeTruthy();
    expect(screen.getByTestId('clinical-notes-list')).toBeTruthy();
    expect(screen.getByTestId('clinical-note-n-1')).toBeTruthy();

    // Trust readout prefers the Beta mean alpha/(alpha+beta) = 3/4 = 0.75.
    expect(screen.getByTestId('clinical-stream-trust').textContent).toContain('0.75');

    // HXI calls omit as_agent_id (Captain authority at the server gate).
    const urls = fm.mock.calls.map(c => String(c[0]));
    expect(urls.some(u => u.includes('/api/counselor/clinical/agent-data'))).toBe(true);
    expect(urls.every(u => !u.includes('as_agent_id'))).toBe(true);
  });

  it('write_box_posts_typed_body_and_optimistically_prepends', async () => {
    const fm = routedFetch({
      roster: ROSTER,
      clinical: { body: CLINICAL },
      notes: { body: NOTES },
      notePostId: 'note-2',
    });
    render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => screen.getByTestId('clinical-agent-row-agent-data'));
    fireEvent.click(screen.getByTestId('clinical-agent-row-agent-data'));
    await waitFor(() => screen.getByTestId('clinical-note-input'));

    fireEvent.change(screen.getByTestId('clinical-note-input'), {
      target: { value: 'New observation' },
    });
    fireEvent.click(screen.getByTestId('clinical-note-submit'));

    await waitFor(() => {
      const post = fm.mock.calls.find(c => (c[1] as RequestInit | undefined)?.method === 'POST');
      expect(post).toBeTruthy();
      expect(String(post![0])).toBe('/api/counselor/notes/agent-data');
      expect(JSON.parse((post![1] as RequestInit).body as string).body).toBe('New observation');
    });
    await waitFor(() => {
      expect(screen.getByTestId('clinical-note-note-2')).toBeTruthy();
    });
  });

  it('server_403_swaps_to_unauthorized', async () => {
    const fm = routedFetch({ roster: ROSTER, clinical: { status: 403 } });
    render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => screen.getByTestId('clinical-agent-row-agent-data'));
    fireEvent.click(screen.getByTestId('clinical-agent-row-agent-data'));
    await waitFor(() => {
      expect(screen.getByTestId('clinical-unauthorized')).toBeTruthy();
    });
  });

  it('client_unauthorized_placeholder_does_not_fetch', () => {
    const fm = vi.fn();
    render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} authorized={false} />);
    expect(screen.getByTestId('clinical-unauthorized')).toBeTruthy();
    expect(fm).not.toHaveBeenCalled();
  });

  it('empty_notes_degrade_to_placeholder', async () => {
    const fm = routedFetch({
      roster: ROSTER,
      clinical: { body: CLINICAL },
      notes: { body: { notes: [] } },
    });
    render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => screen.getByTestId('clinical-agent-row-agent-data'));
    fireEvent.click(screen.getByTestId('clinical-agent-row-agent-data'));
    await waitFor(() => {
      expect(screen.getByTestId('clinical-notes-empty')).toBeTruthy();
    });
  });

  it('contains_no_emoji_glyphs', async () => {
    const fm = routedFetch({ roster: ROSTER, clinical: { body: CLINICAL }, notes: { body: NOTES } });
    const { container } = render(<ClinicalPanel fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => screen.getByTestId('clinical-agent-row-agent-data'));
    fireEvent.click(screen.getByTestId('clinical-agent-row-agent-data'));
    await waitFor(() => screen.getByTestId('clinical-stream-trust'));
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
