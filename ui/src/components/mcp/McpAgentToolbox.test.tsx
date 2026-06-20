/** AD-1019d vitest — resolved agent-toolbox surface.
 *
 * Consumes the AD-1019 access endpoint (per enabled server) via the `deps`
 * injection (no global fetch mock, no real network). Asserts: selecting an
 * agent iterates only enabled servers and lists only enabled tools, the
 * 3-bucket provenance badge (tool/server→agent, department→department,
 * default→ship), per-server honest-degrade on an access failure, the
 * management-disabled (servers GET 404) state, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { McpAgentToolbox, type McpAgentToolboxDeps } from './McpAgentToolbox';
import type { RosterAgent, McpAgentAccessResult } from './McpAgentAccess';
import type { McpServer, McpServersResult } from './McpServersPanel';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeRoster(): RosterAgent[] {
  return [{ agent_id: 'agent-1', agent_type: 'science_officer', callsign: 'Spock', department: 'science' }];
}

function srv(id: string, name: string, enabled: boolean): McpServer {
  return {
    id, name, type: 'http', url: '', headers: {}, command: '', args: [], env: {}, cwd: '',
    timeout_seconds: null, enabled, auth_kind: 'none', credential_ref: '', auth_header_name: '',
    auth_scheme: '', auth_env_var: '', oauth_json: '', created_at: 0, updated_at: 0,
  };
}

function makeServers(): McpServersResult {
  return { servers: [srv('srv-1', 'github-mcp', true), srv('srv-2', 'off-mcp', false)], disabled: false };
}

function makeDeps(over: Partial<McpAgentToolboxDeps> = {}): McpAgentToolboxDeps {
  return {
    fetchRoster: vi.fn(async () => makeRoster()),
    fetchServers: vi.fn(async () => makeServers()),
    fetchAgentAccess: vi.fn(async (): Promise<McpAgentAccessResult> => ({
      server_enabled: true,
      tools: [
        { name: 'echo', enabled: true, source: 'tool' },
        { name: 'deploy', enabled: true, source: 'department' },
        { name: 'ping', enabled: true, source: 'default' },
        { name: 'hidden', enabled: false, source: 'default' },
      ],
    })),
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-1019d McpAgentToolbox', () => {
  it('resolves the toolbox across enabled servers only, filtering disabled tools', async () => {
    const deps = makeDeps();
    render(<McpAgentToolbox deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-toolbox-agent-select'));
    fireEvent.change(screen.getByTestId('mcp-toolbox-agent-select'), { target: { value: 'agent-1' } });
    await waitFor(() => screen.getByTestId('mcp-toolbox-tool-github-mcp-echo'));
    // Only the enabled server (srv-1) was queried; the disabled srv-2 was skipped.
    expect(deps.fetchAgentAccess).toHaveBeenCalledWith('srv-1', 'agent-1');
    expect(deps.fetchAgentAccess).not.toHaveBeenCalledWith('srv-2', 'agent-1');
    // The disabled tool 'hidden' is filtered out of the toolbox.
    expect(screen.queryByTestId('mcp-toolbox-tool-github-mcp-hidden')).toBeNull();
  });

  it('maps the 3 provenance buckets (agent / department / ship)', async () => {
    const deps = makeDeps();
    render(<McpAgentToolbox deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-toolbox-agent-select'));
    fireEvent.change(screen.getByTestId('mcp-toolbox-agent-select'), { target: { value: 'agent-1' } });
    await waitFor(() => screen.getByTestId('mcp-toolbox-source-github-mcp-echo'));
    expect(screen.getByTestId('mcp-toolbox-source-github-mcp-echo').textContent).toContain('agent');
    expect(screen.getByTestId('mcp-toolbox-source-github-mcp-deploy').textContent).toContain('department');
    expect(screen.getByTestId('mcp-toolbox-source-github-mcp-ping').textContent).toContain('ship');
    // The department bucket renders the green provenance color.
    expect((screen.getByTestId('mcp-toolbox-source-github-mcp-deploy') as HTMLElement).style.color).toBe('rgb(64, 184, 144)');
  });

  it('honest-degrades per server when an access fetch fails (never throws)', async () => {
    const deps = makeDeps({ fetchAgentAccess: vi.fn(async () => { throw new Error('nope'); }) });
    render(<McpAgentToolbox deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-toolbox-agent-select'));
    fireEvent.change(screen.getByTestId('mcp-toolbox-agent-select'), { target: { value: 'agent-1' } });
    await waitFor(() => expect(screen.getByTestId('mcp-toolbox-server-error-github-mcp')).toBeTruthy());
  });

  it('shows the management-disabled state when servers GET 404', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: true })) });
    render(<McpAgentToolbox deps={deps} />);
    await waitFor(() => expect(screen.getByTestId('mcp-toolbox-disabled')).toBeTruthy());
  });

  it('uses NO emoji (HXI #3)', async () => {
    const deps = makeDeps();
    const { container } = render(<McpAgentToolbox deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-toolbox-agent-select'));
    fireEvent.change(screen.getByTestId('mcp-toolbox-agent-select'), { target: { value: 'agent-1' } });
    await waitFor(() => screen.getByTestId('mcp-toolbox-tool-github-mcp-echo'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
