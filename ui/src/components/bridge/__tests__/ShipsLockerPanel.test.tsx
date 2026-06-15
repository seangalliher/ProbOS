// AD-1001b: ShipsLockerPanel tests. The global capabilities catalog overlay
// (Ship's Locker), bound to GET /api/tools/catalog (AD-1001a). Uses the `deps`
// injection so no global fetch mock is needed. HXI #3 (no emoji) asserted.
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { ShipsLockerPanel, type Catalog } from '../ShipsLockerPanel';
import { useStore } from '../../../store/useStore';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeCatalog(): Catalog {
  return {
    tools: [
      { id: 'file_reader', name: 'File Reader', origin: 'built_in', held_by: ['ezri', 'yeo'] },
      { id: 'db_query', name: 'DB Query', origin: 'mcp', held_by: [] },
    ],
    skills: [
      { id: 'triage', name: 'Triage', department: 'medical', held_by: ['bones'] },
    ],
    mesh_intents: [
      { id: 'run_python', name: 'run_python', requires_consensus: true, tier: 'core', origin: 'built_in', reachable: true },
      { id: 'http_fetch', name: 'http_fetch', requires_consensus: false, tier: 'core', origin: 'built_in', reachable: true },
    ],
    mcp_servers: [{ url: 'http://localhost:9000', origin: 'mcp' }],
    counts: { tools: 2, skills: 1, mesh_intents: 2, mcp_servers: 1 },
  };
}

beforeEach(() => {
  useStore.setState({ shipsLockerOpen: true });
});

afterEach(() => {
  useStore.setState({ shipsLockerOpen: false });
  cleanup();
});

describe('AD-1001b ShipsLockerPanel', () => {
  it('renders nothing when closed', () => {
    useStore.setState({ shipsLockerOpen: false });
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const { container } = render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    expect(container.firstChild).toBeNull();
    expect(fetchCatalog).not.toHaveBeenCalled();
  });

  it('shows the loading placeholder before the fetch resolves', () => {
    const fetchCatalog = vi.fn(() => new Promise<never>(() => {}));
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    expect(screen.getByTestId('ships-locker-loading')).toBeTruthy();
  });

  it('renders all four catalog sections with counts', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('locker-tool-file_reader'));
    const panel = screen.getByTestId('ships-locker-panel');
    expect(panel.textContent).toContain('TOOLS (2)');
    expect(panel.textContent).toContain('SKILLS (1)');
    expect(panel.textContent).toContain('CAPABILITIES (mesh) (2)');
    expect(panel.textContent).toContain('MCP SERVERS (1)');
    expect(screen.getByTestId('locker-skill-triage')).toBeTruthy();
    expect(screen.getByTestId('locker-mesh-run_python')).toBeTruthy();
    expect(screen.getByTestId('locker-mcp-http://localhost:9000')).toBeTruthy();
  });

  it('shows who-holds-what + origin per tool', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('locker-tool-file_reader'));
    const fr = screen.getByTestId('locker-tool-file_reader');
    expect(fr.textContent).toContain('built-in');
    expect(fr.textContent).toContain('ezri, yeo');
    const db = screen.getByTestId('locker-tool-db_query');
    expect(db.textContent).toContain('MCP');
    expect(db.textContent).toContain('no explicit grants');
  });

  it('flags consensus on write mesh intents only', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('locker-mesh-run_python'));
    expect(screen.getByTestId('locker-mesh-run_python').textContent).toContain('consensus');
    expect(screen.getByTestId('locker-mesh-http_fetch').textContent).not.toContain('consensus');
  });

  it('closes via the X button (clears the store flag)', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('ships-locker-panel'));
    fireEvent.click(screen.getByTestId('ships-locker-close'));
    expect(useStore.getState().shipsLockerOpen).toBe(false);
  });

  it('closes on Escape', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('ships-locker-panel'));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useStore.getState().shipsLockerOpen).toBe(false);
  });

  it('shows an error state when the fetch rejects', async () => {
    const fetchCatalog = vi.fn(async () => { throw new Error('boom'); });
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => expect(screen.getByTestId('ships-locker-error')).toBeTruthy());
  });

  it('renders empty MCP copy when none configured', async () => {
    const fetchCatalog = vi.fn(async () => ({ ...makeCatalog(), mcp_servers: [], counts: { ...makeCatalog().counts, mcp_servers: 0 } }));
    render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('ships-locker-panel'));
    expect(screen.getByTestId('ships-locker-panel').textContent).toContain('No MCP servers configured.');
  });

  it('uses NO emoji (HXI #3)', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const { container } = render(<ShipsLockerPanel deps={{ fetchCatalog }} />);
    await waitFor(() => screen.getByTestId('ships-locker-panel'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });

  // ── AD-1003d: installed Capability Packs section ──────────────────────
  it('shows the disabled note when packs are off (default)', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const fetchPacks = vi.fn(async () => ({ enabled: false, packs: [], counts: { total: 0, valid: 0, error: 0 } }));
    render(<ShipsLockerPanel deps={{ fetchCatalog, fetchPacks }} />);
    await waitFor(() => screen.getByTestId('ships-locker-panel'));
    await waitFor(() => expect(screen.getByTestId('locker-packs-disabled')).toBeTruthy());
    expect(screen.getByTestId('ships-locker-panel').textContent).toContain('INSTALLED PACKS (0)');
  });

  it('lists installed packs (valid + invalid) when enabled', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const fetchPacks = vi.fn(async () => ({
      enabled: true,
      counts: { total: 2, valid: 1, error: 1 },
      packs: [
        { name: 'dev-tools', version: '1.0.0', description: 'dev utilities', ok: true, has_hooks: true, has_mcp: false },
        { name: 'broken', ok: false, error: 'invalid' },
      ],
    }));
    render(<ShipsLockerPanel deps={{ fetchCatalog, fetchPacks }} />);
    await waitFor(() => screen.getByTestId('locker-pack-dev-tools'));
    expect(screen.getByTestId('ships-locker-panel').textContent).toContain('INSTALLED PACKS (2)');
    expect(screen.getByTestId('locker-pack-dev-tools').textContent).toContain('v1.0.0');
    expect(screen.getByTestId('locker-pack-dev-tools').textContent).toContain('hooks');
    expect(screen.getByTestId('locker-pack-broken').textContent).toContain('invalid manifest');
  });

  it('packs honest-degrade does not break the catalog', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const fetchPacks = vi.fn(async () => { throw new Error('packs down'); });
    render(<ShipsLockerPanel deps={{ fetchCatalog, fetchPacks }} />);
    // the catalog still renders even though the packs fetch threw
    await waitFor(() => screen.getByTestId('locker-tool-file_reader'));
    await waitFor(() => expect(screen.getByTestId('locker-packs-disabled')).toBeTruthy());
  });

  // ── AD-1003f: expandable pack component preview ───────────────────────
  function enabledPacks() {
    return {
      enabled: true,
      counts: { total: 1, valid: 1, error: 0 },
      packs: [{ name: 'dev-tools', version: '1.0.0', description: 'dev', ok: true, has_hooks: false, has_mcp: false }],
    };
  }

  it('expands a valid pack to show its declared components', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const fetchPacks = vi.fn(async () => enabledPacks());
    const fetchPackDetail = vi.fn(async (name: string) => ({
      name, has_hooks: false, has_mcp: false,
      skills: [{ name: 'lint', rel: 'skills/lint' }],
      agents: [{ name: 'reviewer', rel: 'agents/reviewer.md' }],
      counts: { skills: 1, agents: 1 },
    }));
    render(<ShipsLockerPanel deps={{ fetchCatalog, fetchPacks, fetchPackDetail }} />);
    await waitFor(() => screen.getByTestId('locker-pack-expand-dev-tools'));
    fireEvent.click(screen.getByTestId('locker-pack-expand-dev-tools'));
    await waitFor(() => expect(fetchPackDetail).toHaveBeenCalledWith('dev-tools'));
    await waitFor(() => {
      const detail = screen.getByTestId('locker-pack-detail-dev-tools');
      expect(detail.textContent).toContain('lint');
      expect(detail.textContent).toContain('reviewer');
    });
  });

  it('collapses an expanded pack on a second click', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const fetchPacks = vi.fn(async () => enabledPacks());
    const fetchPackDetail = vi.fn(async (name: string) => ({ name, skills: [], agents: [], counts: { skills: 0, agents: 0 } }));
    render(<ShipsLockerPanel deps={{ fetchCatalog, fetchPacks, fetchPackDetail }} />);
    await waitFor(() => screen.getByTestId('locker-pack-expand-dev-tools'));
    fireEvent.click(screen.getByTestId('locker-pack-expand-dev-tools'));
    await waitFor(() => screen.getByTestId('locker-pack-detail-dev-tools'));
    fireEvent.click(screen.getByTestId('locker-pack-expand-dev-tools'));
    await waitFor(() => expect(screen.queryByTestId('locker-pack-detail-dev-tools')).toBeNull());
  });

  it('shows the no-components note for a pack with no declared components', async () => {
    const fetchCatalog = vi.fn(async () => makeCatalog());
    const fetchPacks = vi.fn(async () => enabledPacks());
    const fetchPackDetail = vi.fn(async (name: string) => ({ name, skills: [], agents: [], counts: { skills: 0, agents: 0 } }));
    render(<ShipsLockerPanel deps={{ fetchCatalog, fetchPacks, fetchPackDetail }} />);
    await waitFor(() => screen.getByTestId('locker-pack-expand-dev-tools'));
    fireEvent.click(screen.getByTestId('locker-pack-expand-dev-tools'));
    await waitFor(() => expect(screen.getByTestId('locker-pack-detail-dev-tools').textContent).toContain('No declared components'));
  });
});
