// AD-983c: CapabilityPanel render + toggle tests. The Captain surface for
// per-agent tool/skill enablement (AD-983 Copilot-parity epic, generalizing
// the AD-982 vision toggle). Uses the `deps` injection so no global fetch mock
// is needed. HXI #3 (no emoji) is asserted.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { CapabilityPanel, type AgentCapability, type MeshIntent } from '../CapabilityPanel';

afterEach(cleanup);

// Matches any emoji / pictographic codepoint (HXI #3 guard).
const EMOJI = /\p{Extended_Pictographic}/u;

function makeCaps(): { tools: AgentCapability[]; skills: AgentCapability[]; mesh_intents: MeshIntent[] } {
  return {
    tools: [
      { id: 'file_reader', name: 'File Reader', granted: true, source: 'role_default', origin: 'built_in' },
      { id: 'web_search', name: 'Web Search', granted: false, source: 'restriction', origin: 'mcp' },
    ],
    skills: [
      { id: 'summarize', name: 'Summarize', granted: true, source: 'grant' },
      { id: 'translate', name: 'Translate', granted: false, source: 'dept_default' },
    ],
    mesh_intents: [
      { id: 'run_python', name: 'run_python', description: 'Run a script', requires_consensus: true, tier: 'core', origin: 'built_in', reachable: true },
      { id: 'http_fetch', name: 'http_fetch', description: 'Fetch a URL', requires_consensus: false, tier: 'core', origin: 'built_in', reachable: true },
    ],
  };
}

describe('AD-983c CapabilityPanel', () => {
  it('shows the loading placeholder before the fetch resolves', () => {
    const fetchCapabilities = vi.fn(() => new Promise<never>(() => {})); // never resolves
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    expect(screen.getByTestId('cap-panel-loading')).toBeTruthy();
  });

  it('renders TOOLS and SKILLS sections with counts and rows', async () => {
    const caps = makeCaps();
    const fetchCapabilities = vi.fn(async () => caps);
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);

    await waitFor(() => expect(screen.getByTestId('capability-panel')).toBeTruthy());
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('TOOLS (2)');
    expect(panel.textContent).toContain('SKILLS (2)');
    expect(screen.getByTestId('cap-row-tool-file_reader')).toBeTruthy();
    expect(screen.getByTestId('cap-row-skill-translate')).toBeTruthy();
  });

  it('reflects granted state On/Off and aria-pressed per row', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));

    const granted = screen.getByTestId('cap-toggle-tool-file_reader');
    const ungranted = screen.getByTestId('cap-toggle-tool-web_search');
    expect(granted.textContent).toBe('On');
    expect(granted.getAttribute('aria-pressed')).toBe('true');
    expect(ungranted.textContent).toBe('Off');
    expect(ungranted.getAttribute('aria-pressed')).toBe('false');
  });

  it('renders human source labels (grant / restriction / role_default / dept_default)', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('granted');
    expect(panel.textContent).toContain('restricted');
    expect(panel.textContent).toContain('role default');
    expect(panel.textContent).toContain('dept default');
  });

  it('optimistically toggles a tool on and POSTs {kind, id, enabled}', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    const setCapability = vi.fn(async () => true);
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities, setCapability }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));

    const toggle = screen.getByTestId('cap-toggle-tool-web_search');
    expect(toggle.textContent).toBe('Off');
    fireEvent.click(toggle);

    // optimistic flip is synchronous
    expect(toggle.textContent).toBe('On');
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    expect(setCapability).toHaveBeenCalledWith('kirk', 'tool', 'web_search', true);
  });

  it('reverts the toggle when the POST fails', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    const setCapability = vi.fn(async () => false); // server rejects
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities, setCapability }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));

    const toggle = screen.getByTestId('cap-toggle-skill-translate');
    expect(toggle.textContent).toBe('Off');
    fireEvent.click(toggle);
    // optimistic on
    expect(toggle.textContent).toBe('On');
    // reverts after the failed POST resolves
    await waitFor(() => expect(toggle.textContent).toBe('Off'));
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
  });

  it('shows an error placeholder when the fetch rejects', async () => {
    const fetchCapabilities = vi.fn(async () => { throw new Error('boom'); });
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => expect(screen.getByTestId('cap-panel-error')).toBeTruthy());
  });

  it('renders empty-state copy when an agent has no tools or skills', async () => {
    const fetchCapabilities = vi.fn(async () => ({ tools: [], skills: [], mesh_intents: [] }));
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('TOOLS (0)');
    // AD-1006: the empty-tools state explains what tools are (resolves the
    // "0 tools / nothing feels new" confusion), not a bare "No tools.".
    expect(screen.getByTestId('cap-tools-empty').textContent).toContain('callable');
    expect(panel.textContent).toContain('SKILLS (0)');
    expect(panel.textContent).toContain('No skills.');
  });

  it('uses NO emoji (HXI #3 — stroke/SVG/text only)', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const panel = screen.getByTestId('capability-panel');
    expect(EMOJI.test(panel.textContent || '')).toBe(false);
    expect(EMOJI.test(panel.innerHTML)).toBe(false);
  });

  it('refetches when the agentId changes', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    const { rerender } = render(
      <CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />,
    );
    await waitFor(() => screen.getByTestId('capability-panel'));
    expect(fetchCapabilities).toHaveBeenCalledWith('kirk');

    rerender(<CapabilityPanel agentId="spock" deps={{ fetchCapabilities }} />);
    await waitFor(() => expect(fetchCapabilities).toHaveBeenCalledWith('spock'));
  });

  // ── AD-1000a/b: provenance + mesh-intent visibility ────────────────────
  it('renders the CAPABILITIES (mesh) section with rows', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const panel = screen.getByTestId('capability-panel');
    // AD-1006: neither test intent carries served=true, so both land in CAN REQUEST.
    expect(panel.textContent).toContain('CAPABILITIES — CAN REQUEST (2)');
    expect(panel.textContent).toContain('CAPABILITIES — SERVES (0)');
    expect(screen.getByTestId('mesh-row-run_python')).toBeTruthy();
    expect(screen.getByTestId('mesh-row-http_fetch')).toBeTruthy();
  });

  it('flags a write mesh intent with a consensus badge', async () => {
    const caps = makeCaps();
    caps.mesh_intents[0].served = true;  // keep run_python read-only for this check
    const fetchCapabilities = vi.fn(async () => caps);
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    // run_python requires consensus; http_fetch does not.
    expect(screen.getByTestId('mesh-consensus-run_python')).toBeTruthy();
    expect(screen.queryByTestId('mesh-consensus-http_fetch')).toBeNull();
  });

  it('shows the tool origin taxonomy (built-in / MCP)', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    expect(screen.getByTestId('cap-origin-tool-file_reader').textContent).toBe('built-in');
    expect(screen.getByTestId('cap-origin-tool-web_search').textContent).toBe('MCP');
  });

  it('CAN REQUEST mesh rows are toggleable; SERVES rows are not (AD-1008)', async () => {
    const caps = makeCaps();
    caps.mesh_intents[0].served = true;   // run_python = served -> read-only
    // http_fetch stays CAN REQUEST -> toggleable
    const fetchCapabilities = vi.fn(async () => caps);
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    expect(screen.queryByTestId('mesh-toggle-run_python')).toBeNull();   // served
    expect(screen.getByTestId('mesh-toggle-http_fetch')).toBeTruthy();   // can-request
  });

  it('toggles a CAN REQUEST capability and POSTs kind=capability (AD-1008)', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    const setCapability = vi.fn(async () => true);
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities, setCapability }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const toggle = screen.getByTestId('mesh-toggle-http_fetch');
    expect(toggle.textContent).toBe('On');   // granted defaults to true
    fireEvent.click(toggle);
    expect(toggle.textContent).toBe('Off');  // optimistic disable
    expect(setCapability).toHaveBeenCalledWith('kirk', 'capability', 'http_fetch', false);
  });

  it('reverts a capability toggle when the POST fails (AD-1008)', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps());
    const setCapability = vi.fn(async () => false);
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities, setCapability }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const toggle = screen.getByTestId('mesh-toggle-http_fetch');
    fireEvent.click(toggle);
    expect(toggle.textContent).toBe('Off');                 // optimistic
    await waitFor(() => expect(toggle.textContent).toBe('On'));  // reverts
  });

  it('renders empty mesh copy when none are reachable', async () => {
    const fetchCapabilities = vi.fn(async () => ({ ...makeCaps(), mesh_intents: [] }));
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('CAPABILITIES — CAN REQUEST (0)');
    expect(panel.textContent).toContain('No mesh capabilities.');
  });

  // ── AD-1006: serves vs can-request split ─────────────────────────────
  it('splits served intents from the ship-wide reachable set', async () => {
    const caps = makeCaps();
    // The agent SERVES run_python; http_fetch is ship-wide reachable only.
    caps.mesh_intents[0].served = true;
    const fetchCapabilities = vi.fn(async () => caps);
    render(<CapabilityPanel agentId="counselor" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('CAPABILITIES — SERVES (1)');
    expect(panel.textContent).toContain('CAPABILITIES — CAN REQUEST (1)');
    // Both still render their rows; the split is presentational, not a filter.
    expect(screen.getByTestId('mesh-row-run_python')).toBeTruthy();
    expect(screen.getByTestId('mesh-row-http_fetch')).toBeTruthy();
  });

  it('shows the no-specialty empty state when the agent serves nothing', async () => {
    const fetchCapabilities = vi.fn(async () => makeCaps()); // no served flags
    render(<CapabilityPanel agentId="kirk" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    expect(screen.getByTestId('cap-serves-empty').textContent).toContain('skills and reasoning');
  });
});
