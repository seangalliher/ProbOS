/** AD-1019d vitest — department-locker authoring surface.
 *
 * Consumes the AD-1019e department endpoints via the `deps` injection (no global
 * fetch mock, no real network). Asserts: the department picker is the distinct
 * set of roster departments, stocking a single tool + a whole server (POST
 * stock), the locker list render, unstocking (DELETE unstock), the
 * management-disabled (GET 404) state, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import {
  McpDepartmentLockers,
  type McpDepartmentLockersDeps,
  type DepartmentGrantsResult,
} from './McpDepartmentLockers';
import type { RosterAgent } from './McpAgentAccess';
import type { McpServer, McpServersResult } from './McpServersPanel';
import type { McpToolRiskResult } from './McpToolRisk';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeRoster(): RosterAgent[] {
  return [
    { agent_id: 'a1', agent_type: 'science_officer', department: 'science' },
    { agent_id: 'a2', agent_type: 'engineer', department: 'engineering' },
    { agent_id: 'a3', agent_type: 'engineer-2', department: 'engineering' }, // duplicate dept
    { agent_id: 'a4', agent_type: 'drifter', department: null }, // no dept → dropped
  ];
}

function makeServer(): McpServer {
  return {
    id: 'srv-1', name: 'github-mcp', type: 'http', url: '', headers: {}, command: '',
    args: [], env: {}, cwd: '', timeout_seconds: null, enabled: true, auth_kind: 'none',
    credential_ref: '', auth_header_name: '', auth_scheme: '', auth_env_var: '',
    oauth_json: '', created_at: 0, updated_at: 0,
  };
}

function makeServers(): McpServersResult {
  return { servers: [makeServer()], disabled: false };
}

function makeGrants(over: Partial<DepartmentGrantsResult> = {}): DepartmentGrantsResult {
  return {
    grants: [
      { grant_id: 'g1', department: 'science', tool_id: 'mcp:github-mcp:echo', is_restriction: false, enabled: true },
    ],
    ...over,
  };
}

function makeDeps(over: Partial<McpDepartmentLockersDeps> = {}): McpDepartmentLockersDeps {
  return {
    fetchGrants: vi.fn(async () => makeGrants()),
    fetchRoster: vi.fn(async () => makeRoster()),
    fetchServers: vi.fn(async () => makeServers()),
    fetchServerTools: vi.fn(async (): Promise<McpToolRiskResult> => ({
      tools: [{ name: 'echo' }, { name: 'deploy' }], count: 2,
    })),
    stock: vi.fn(async () => {}),
    unstock: vi.fn(async () => {}),
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-1019d McpDepartmentLockers', () => {
  it('builds the department picker from distinct roster departments (sorted)', async () => {
    const deps = makeDeps();
    render(<McpDepartmentLockers deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-locker-dept-select'));
    const sel = screen.getByTestId('mcp-locker-dept-select') as HTMLSelectElement;
    const opts = Array.from(sel.querySelectorAll('option')).map((o) => o.value).filter(Boolean);
    expect(opts).toEqual(['engineering', 'science']);
  });

  it('stocks a single tool into a department locker (POST stock)', async () => {
    const deps = makeDeps();
    render(<McpDepartmentLockers deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-locker-stock'));
    fireEvent.change(screen.getByTestId('mcp-locker-dept-select'), { target: { value: 'science' } });
    fireEvent.change(screen.getByTestId('mcp-locker-server-select'), { target: { value: 'srv-1' } });
    await waitFor(() => expect(deps.fetchServerTools).toHaveBeenCalledWith('srv-1'));
    // Wait for the tool dropdown to be populated, then pick a tool.
    await waitFor(() => {
      const tsel = screen.getByTestId('mcp-locker-tool-select') as HTMLSelectElement;
      expect(Array.from(tsel.querySelectorAll('option')).some((o) => o.value === 'echo')).toBe(true);
    });
    fireEvent.change(screen.getByTestId('mcp-locker-tool-select'), { target: { value: 'echo' } });
    fireEvent.click(screen.getByTestId('mcp-locker-stock'));
    await waitFor(() => expect(deps.stock).toHaveBeenCalledWith('science', { server_id: 'srv-1', tool: 'echo', enabled: true }));
  });

  it('stocks a whole server when no tool is chosen', async () => {
    const deps = makeDeps();
    render(<McpDepartmentLockers deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-locker-stock'));
    fireEvent.change(screen.getByTestId('mcp-locker-dept-select'), { target: { value: 'engineering' } });
    fireEvent.change(screen.getByTestId('mcp-locker-server-select'), { target: { value: 'srv-1' } });
    fireEvent.click(screen.getByTestId('mcp-locker-stock'));
    await waitFor(() => expect(deps.stock).toHaveBeenCalledWith('engineering', { server_id: 'srv-1', tool: undefined, enabled: true }));
  });

  it('renders the locker grants and unstocks one (DELETE unstock)', async () => {
    const deps = makeDeps();
    render(<McpDepartmentLockers deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-locker-grant-g1'));
    expect(screen.getByTestId('mcp-locker-grant-g1').textContent).toContain('mcp:github-mcp:echo');
    fireEvent.click(screen.getByTestId('mcp-locker-unstock-g1'));
    await waitFor(() => expect(deps.unstock).toHaveBeenCalledWith('g1'));
  });

  it('shows the management-disabled state on a GET 404 (fetchGrants.disabled)', async () => {
    const deps = makeDeps({ fetchGrants: vi.fn(async () => ({ grants: [], disabled: true })) });
    render(<McpDepartmentLockers deps={deps} />);
    await waitFor(() => expect(screen.getByTestId('mcp-lockers-disabled')).toBeTruthy());
  });

  it('uses NO emoji (HXI #3)', async () => {
    const deps = makeDeps();
    const { container } = render(<McpDepartmentLockers deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-locker-grant-g1'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
