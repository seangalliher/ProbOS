/** AD-1019a vitest — per-agent / per-tool MCP enablement surface.
 *
 * Consumes the AD-1019 enablement endpoints via the `deps` injection (no global
 * fetch mock, no real network). Asserts: roster render, server enable/disable
 * (POST {enabled}), per-tool enable/disable (POST {enabled,tool}), reset
 * (DELETE ?tool=), the source badge (tool/server/default), honest-degrade on a
 * roster/access fetch failure, the management-disabled (GET 404) state, and the
 * HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import {
  McpAgentAccess,
  type McpAgentAccessDeps,
  type RosterAgent,
  type McpAgentAccessResult,
} from './McpAgentAccess';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeRoster(): RosterAgent[] {
  return [
    { agent_id: 'agent-1', agent_type: 'science_officer', callsign: 'Spock', post: 'Science', department: 'science' },
    { agent_id: 'agent-2', agent_type: 'engineer', callsign: 'Scott', post: 'Engineering', department: 'engineering' },
  ];
}

function makeAccess(over: Partial<McpAgentAccessResult> = {}): McpAgentAccessResult {
  return {
    server_enabled: false,
    tools: [
      { name: 'echo', enabled: false, source: 'default' },
      { name: 'slow', enabled: true, source: 'tool' },
    ],
    ...over,
  };
}

function makeDeps(over: Partial<McpAgentAccessDeps> = {}): McpAgentAccessDeps {
  return {
    fetchRoster: vi.fn(async () => makeRoster()),
    fetchTools: vi.fn(async () => ({ tools: [{ name: 'echo' }, { name: 'slow' }], count: 2 })),
    fetchAgentAccess: vi.fn(async () => makeAccess()),
    setAccess: vi.fn(async () => {}),
    clearAccess: vi.fn(async () => {}),
    ...over,
  };
}

function renderPanel(deps: McpAgentAccessDeps) {
  return render(<McpAgentAccess serverId="srv-1" serverName="github-mcp" deps={deps} />);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-1019a McpAgentAccess', () => {
  it('renders the crew roster from the injected fetchRoster + fetchTools', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-row-agent-1'));
    expect(screen.getByTestId('mcp-access-row-agent-1').textContent).toContain('Spock');
    expect(screen.getByTestId('mcp-access-row-agent-2').textContent).toContain('Scott');
    expect(deps.fetchRoster).toHaveBeenCalled();
    expect(deps.fetchTools).toHaveBeenCalled();
  });

  it('enables a server for an agent (POST {enabled:true})', async () => {
    const deps = makeDeps(); // default server_enabled=false → click enables
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-github-mcp-agent-1'));
    await waitFor(() => expect(deps.setAccess).toHaveBeenCalledWith('agent-1', { enabled: true }));
  });

  it('disables a server for an agent (POST {enabled:false})', async () => {
    const deps = makeDeps({ fetchAgentAccess: vi.fn(async () => makeAccess({ server_enabled: true })) });
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    // Expand to load the agent's resolved access (server_enabled=true).
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => expect(screen.getByTestId('mcp-access-github-mcp-agent-1').textContent).toContain('Enabled'));
    fireEvent.click(screen.getByTestId('mcp-access-github-mcp-agent-1'));
    await waitFor(() => expect(deps.setAccess).toHaveBeenCalledWith('agent-1', { enabled: false }));
  });

  it('enables a single tool for an agent (POST {enabled:true,tool})', async () => {
    const deps = makeDeps(); // echo enabled:false → click enables
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => screen.getByTestId('mcp-access-tool-github-mcp-agent-1-echo'));
    fireEvent.click(screen.getByTestId('mcp-access-tool-github-mcp-agent-1-echo'));
    await waitFor(() => expect(deps.setAccess).toHaveBeenCalledWith('agent-1', { enabled: true, tool: 'echo' }));
  });

  it('disables a single tool for an agent (POST {enabled:false,tool})', async () => {
    const deps = makeDeps(); // slow enabled:true → click disables
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => screen.getByTestId('mcp-access-tool-github-mcp-agent-1-slow'));
    fireEvent.click(screen.getByTestId('mcp-access-tool-github-mcp-agent-1-slow'));
    await waitFor(() => expect(deps.setAccess).toHaveBeenCalledWith('agent-1', { enabled: false, tool: 'slow' }));
  });

  it('resets a tool to default (DELETE ?tool=)', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => screen.getByTestId('mcp-access-reset-github-mcp-agent-1-echo'));
    fireEvent.click(screen.getByTestId('mcp-access-reset-github-mcp-agent-1-echo'));
    await waitFor(() => expect(deps.clearAccess).toHaveBeenCalledWith('agent-1', 'echo'));
  });

  it('resets the whole server for an agent (DELETE, no tool)', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-reset-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-reset-github-mcp-agent-1'));
    await waitFor(() => expect(deps.clearAccess).toHaveBeenCalledWith('agent-1', undefined));
  });

  it('shows the source badge for each tool (tool / server / default)', async () => {
    const deps = makeDeps({
      fetchAgentAccess: vi.fn(async () => makeAccess({
        tools: [
          { name: 'echo', enabled: false, source: 'default' },
          { name: 'slow', enabled: true, source: 'tool' },
          { name: 'wide', enabled: true, source: 'server' },
        ],
      })),
    });
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => screen.getByTestId('mcp-access-tool-source-github-mcp-agent-1-echo'));
    expect(screen.getByTestId('mcp-access-tool-source-github-mcp-agent-1-echo').textContent).toContain('default');
    expect(screen.getByTestId('mcp-access-tool-source-github-mcp-agent-1-slow').textContent).toContain('tool');
    expect(screen.getByTestId('mcp-access-tool-source-github-mcp-agent-1-wide').textContent).toContain('server');
  });

  it('honest-degrades to an error note when the roster fetch fails', async () => {
    const deps = makeDeps({ fetchRoster: vi.fn(async () => { throw new Error('boom'); }) });
    renderPanel(deps);
    await waitFor(() => expect(screen.getByTestId('mcp-access-error-srv-1')).toBeTruthy());
    expect(screen.getByTestId('mcp-access-error-srv-1').textContent).toContain('unavailable');
  });

  it('honest-degrades to a row error when an agent access fetch fails', async () => {
    const deps = makeDeps({ fetchAgentAccess: vi.fn(async () => { throw new Error('nope'); }) });
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => expect(screen.getByTestId('mcp-access-row-error-agent-1')).toBeTruthy());
  });

  it('shows the management-disabled state on a GET 404 (fetchTools.disabled)', async () => {
    const deps = makeDeps({ fetchTools: vi.fn(async () => ({ tools: [], count: 0, disabled: true })) });
    renderPanel(deps);
    await waitFor(() => expect(screen.getByTestId('mcp-access-disabled-srv-1')).toBeTruthy());
    expect(screen.getByTestId('mcp-access-disabled-srv-1').textContent).toContain('MCP management is disabled');
  });

  it('uses NO emoji (HXI #3)', async () => {
    const deps = makeDeps();
    const { container } = renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-access-row-agent-1'));
    fireEvent.click(screen.getByTestId('mcp-access-expand-github-mcp-agent-1'));
    await waitFor(() => screen.getByTestId('mcp-access-tool-github-mcp-agent-1-echo'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
