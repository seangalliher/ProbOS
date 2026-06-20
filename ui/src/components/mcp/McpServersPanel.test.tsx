/** AD-1018 vitest — MCP Servers management panel.
 *
 * Consumes the AD-1015 CRUD + AD-1017 auth endpoints via the `deps` injection
 * (no global fetch mock, no real network). Asserts: list/empty/disabled states,
 * create (http + stdio) shape, client-side validation, edit/delete/enable, the
 * test-connection result text, the credential modal (static `putCredential` +
 * **the token never returns to the DOM**), the OAuth `startOAuth` + `window.open`,
 * no secret rendered in a list/detail, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { McpServersPanel, type McpServer, type McpDeps } from './McpServersPanel';
import { useStore } from '../../store/useStore';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeServer(over: Partial<McpServer> = {}): McpServer {
  return {
    id: 'srv-1',
    name: 'github-mcp',
    type: 'http',
    url: 'https://api.example/mcp',
    headers: {},
    command: '',
    args: [],
    env: {},
    cwd: '',
    timeout_seconds: null,
    enabled: true,
    auth_kind: 'none',
    credential_ref: '',
    auth_header_name: 'Authorization',
    auth_scheme: 'Bearer',
    auth_env_var: '',
    oauth_json: '',
    created_at: 0,
    updated_at: 0,
    ...over,
  };
}

function makeDeps(over: Partial<McpDeps> = {}): McpDeps {
  return {
    fetchServers: vi.fn(async () => ({ servers: [makeServer()], disabled: false })),
    createServer: vi.fn(async (input) => makeServer({ id: 'new', ...input })),
    updateServer: vi.fn(async (id, input) => makeServer({ id, ...input })),
    deleteServer: vi.fn(async () => true),
    setEnabled: vi.fn(async (id, enabled) => makeServer({ id, enabled })),
    testServer: vi.fn(async () => ({ ok: true, tool_count: 3 })),
    putCredential: vi.fn(async (id) => makeServer({ id, auth_kind: 'static', credential_ref: `mcp:${id}` })),
    deleteCredential: vi.fn(async (id) => makeServer({ id, auth_kind: 'none', credential_ref: '' })),
    startOAuth: vi.fn(async () => ({ auth_url: 'https://auth.example/authorize?x=1', state: 'st-1' })),
    refreshOAuth: vi.fn(async () => true),
    ...over,
  };
}

beforeEach(() => {
  useStore.setState({ mcpServersOpen: true });
});

afterEach(() => {
  useStore.setState({ mcpServersOpen: false });
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-1018 McpServersPanel', () => {
  it('renders nothing when closed and does not fetch', () => {
    useStore.setState({ mcpServersOpen: false });
    const deps = makeDeps();
    const { container } = render(<McpServersPanel deps={deps} />);
    expect(container.firstChild).toBeNull();
    expect(deps.fetchServers).not.toHaveBeenCalled();
  });

  it('lists servers from the injected fetchServers', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-row-srv-1'));
    const row = screen.getByTestId('mcp-row-srv-1');
    expect(row.textContent).toContain('github-mcp');
    expect(screen.getByTestId('mcp-type-srv-1').textContent).toContain('http');
    expect(screen.getByTestId('mcp-auth-kind-srv-1').textContent).toContain('none');
    expect(row.textContent).toContain('https://api.example/mcp');
  });

  it('shows the empty state when no servers are configured', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: false })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => expect(screen.getByTestId('mcp-empty')).toBeTruthy());
  });

  it('shows the disabled note when management is off (GET 404)', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: true })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => expect(screen.getByTestId('mcp-disabled')).toBeTruthy());
    expect(screen.getByTestId('mcp-disabled').textContent).toContain('MCP management is disabled');
  });

  it('shows the error state when the fetch rejects', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => { throw new Error('boom'); }) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => expect(screen.getByTestId('mcp-error')).toBeTruthy());
  });

  it('creates an http server with the right shape', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: false })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-add'));
    fireEvent.click(screen.getByTestId('mcp-add'));
    fireEvent.change(screen.getByTestId('mcp-form-name'), { target: { value: 'my-server' } });
    fireEvent.change(screen.getByTestId('mcp-form-url'), { target: { value: 'https://h/mcp' } });
    fireEvent.click(screen.getByTestId('mcp-form-submit'));
    await waitFor(() => expect(deps.createServer).toHaveBeenCalledWith({
      name: 'my-server', type: 'http', url: 'https://h/mcp', headers: {},
      command: '', args: [], env: {}, cwd: '', timeout_seconds: null,
    }));
  });

  it('creates a stdio server with command + args', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: false })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-add'));
    fireEvent.click(screen.getByTestId('mcp-add'));
    fireEvent.change(screen.getByTestId('mcp-form-name'), { target: { value: 'local-srv' } });
    fireEvent.change(screen.getByTestId('mcp-form-type'), { target: { value: 'stdio' } });
    fireEvent.change(screen.getByTestId('mcp-form-command'), { target: { value: 'uvx' } });
    fireEvent.change(screen.getByTestId('mcp-form-args'), { target: { value: 'mcp-foo\n--flag' } });
    fireEvent.click(screen.getByTestId('mcp-form-submit'));
    await waitFor(() => expect(deps.createServer).toHaveBeenCalledWith({
      name: 'local-srv', type: 'stdio', url: '', headers: {},
      command: 'uvx', args: ['mcp-foo', '--flag'], env: {}, cwd: '', timeout_seconds: null,
    }));
  });

  it('blocks an invalid (non-kebab) name client-side', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: false })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-add'));
    fireEvent.click(screen.getByTestId('mcp-add'));
    fireEvent.change(screen.getByTestId('mcp-form-name'), { target: { value: 'Bad Name' } });
    fireEvent.change(screen.getByTestId('mcp-form-url'), { target: { value: 'https://h/mcp' } });
    fireEvent.click(screen.getByTestId('mcp-form-submit'));
    expect(screen.getByTestId('mcp-form-error')).toBeTruthy();
    expect(deps.createServer).not.toHaveBeenCalled();
  });

  it('blocks an http server with no URL client-side', async () => {
    const deps = makeDeps({ fetchServers: vi.fn(async () => ({ servers: [], disabled: false })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-add'));
    fireEvent.click(screen.getByTestId('mcp-add'));
    fireEvent.change(screen.getByTestId('mcp-form-name'), { target: { value: 'no-url' } });
    fireEvent.click(screen.getByTestId('mcp-form-submit'));
    expect(screen.getByTestId('mcp-form-error').textContent).toContain('requires a URL');
    expect(deps.createServer).not.toHaveBeenCalled();
  });

  it('edits a server (PUT updateServer)', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-edit-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-edit-srv-1'));
    fireEvent.change(screen.getByTestId('mcp-form-name'), { target: { value: 'renamed-mcp' } });
    fireEvent.click(screen.getByTestId('mcp-form-submit'));
    await waitFor(() => expect(deps.updateServer).toHaveBeenCalled());
    const [calledId, calledInput] = (deps.updateServer as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(calledId).toBe('srv-1');
    expect(calledInput.name).toBe('renamed-mcp');
  });

  it('deletes a server only after the confirm step', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-delete-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-delete-srv-1'));
    expect(deps.deleteServer).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('mcp-delete-confirm-srv-1'));
    await waitFor(() => expect(deps.deleteServer).toHaveBeenCalledWith('srv-1'));
  });

  it('toggles enable/disable through setEnabled', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-toggle-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-toggle-srv-1'));
    await waitFor(() => expect(deps.setEnabled).toHaveBeenCalledWith('srv-1', false));
  });

  it('renders the test-connection OK + tool_count', async () => {
    const deps = makeDeps({ testServer: vi.fn(async () => ({ ok: true, tool_count: 7 })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-test-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-test-srv-1'));
    await waitFor(() => expect(screen.getByTestId('mcp-test-result-srv-1').textContent).toContain('OK · 7 tools'));
  });

  it('renders the test-connection failure', async () => {
    const deps = makeDeps({ testServer: vi.fn(async () => ({ ok: false, error: 'unreachable' })) });
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-test-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-test-srv-1'));
    await waitFor(() => {
      const t = screen.getByTestId('mcp-test-result-srv-1').textContent || '';
      expect(t).toContain('FAILED');
      expect(t).toContain('unreachable');
    });
  });

  it('saves a static credential and never echoes the token back into the DOM', async () => {
    const TOKEN = 'super-secret-token-xyz';
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-auth-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-auth-srv-1'));
    await waitFor(() => screen.getByTestId('mcp-cred-modal'));
    fireEvent.change(screen.getByTestId('mcp-cred-token'), { target: { value: TOKEN } });
    fireEvent.click(screen.getByTestId('mcp-cred-save'));
    await waitFor(() => expect(deps.putCredential).toHaveBeenCalledWith('srv-1', {
      value: TOKEN, header_name: 'Authorization', scheme: 'Bearer', env_var: '',
    }));
    // The modal closes after save; the write-only token must be gone from the DOM.
    await waitFor(() => expect(screen.queryByTestId('mcp-cred-modal')).toBeNull());
    expect(screen.queryByDisplayValue(TOKEN)).toBeNull();
    expect(document.body.textContent).not.toContain(TOKEN);
  });

  it('starts OAuth and opens the consent window', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-auth-srv-1'));
    fireEvent.click(screen.getByTestId('mcp-auth-srv-1'));
    await waitFor(() => screen.getByTestId('mcp-cred-modal'));
    fireEvent.click(screen.getByTestId('mcp-cred-kind-oauth'));
    fireEvent.change(screen.getByTestId('mcp-oauth-client-id'), { target: { value: 'cid' } });
    fireEvent.click(screen.getByTestId('mcp-oauth-connect'));
    await waitFor(() => expect(deps.startOAuth).toHaveBeenCalled());
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('https://auth.example/authorize?x=1', '_blank', expect.any(String)));
  });

  it('does not render any secret value in a list/detail view', async () => {
    const deps = makeDeps({
      fetchServers: vi.fn(async () => ({
        servers: [
          makeServer({ id: 'a', name: 'static-srv', auth_kind: 'static', credential_ref: 'mcp:a' }),
          makeServer({ id: 'b', name: 'oauth-srv', auth_kind: 'oauth', credential_ref: 'mcp:b:oauth', oauth_json: '{"client_id":"cid","authorize_url":"https://x/a"}' }),
        ],
        disabled: false,
      })),
    });
    const { container } = render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-row-a'));
    // The auth state is shown as a badge only.
    expect(screen.getByTestId('mcp-auth-kind-a').textContent).toContain('static');
    expect(screen.getByTestId('mcp-auth-kind-b').textContent).toContain('oauth');
    // No password input is present in the list view (secrets only live in the modal).
    expect(container.querySelectorAll('input[type="password"]').length).toBe(0);
  });

  it('closes via the X button (clears the store flag)', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-servers-panel'));
    fireEvent.click(screen.getByTestId('mcp-close'));
    expect(useStore.getState().mcpServersOpen).toBe(false);
  });

  it('closes on Escape', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-servers-panel'));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useStore.getState().mcpServersOpen).toBe(false);
  });

  it('mounts the Agent access section for an expanded server (AD-1019a)', async () => {
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-row-srv-1'));
    // Collapsed by default; the AD-1019a section mounts only after expansion.
    expect(screen.queryByTestId('mcp-agent-access-srv-1')).toBeNull();
    fireEvent.click(screen.getByTestId('mcp-access-section-srv-1'));
    await waitFor(() => expect(screen.getByTestId('mcp-agent-access-srv-1')).toBeTruthy());
  });

  it('switches views via the tab strip and toggles the tool-risk section (AD-1019d)', async () => {
    // The tab-mounted children + the per-row risk section use their own inline
    // api (global fetch, no deps); stub it to a 404 so they honest-degrade.
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }) as unknown as Response));
    const deps = makeDeps();
    render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-row-srv-1'));
    // Default view is 'servers'.
    expect(screen.getByTestId('mcp-view-servers')).toBeTruthy();

    // Switch to the department lockers view: the server list unmounts.
    fireEvent.click(screen.getByTestId('mcp-view-lockers'));
    await waitFor(() => screen.getByTestId('mcp-lockers-disabled'));
    expect(screen.queryByTestId('mcp-row-srv-1')).toBeNull();

    // Switch to the agent toolbox view.
    fireEvent.click(screen.getByTestId('mcp-view-toolbox'));
    await waitFor(() => screen.getByTestId('mcp-toolbox-disabled'));

    // Back to servers; the row returns and the per-row tool-risk section toggles.
    fireEvent.click(screen.getByTestId('mcp-view-servers'));
    await waitFor(() => screen.getByTestId('mcp-row-srv-1'));
    expect(screen.queryByTestId('mcp-tool-risk-srv-1')).toBeNull();
    fireEvent.click(screen.getByTestId('mcp-risk-section-srv-1'));
    await waitFor(() => screen.getByTestId('mcp-tool-risk-srv-1'));
  });

  it('uses NO emoji (HXI #3)', async () => {
    const deps = makeDeps();
    const { container } = render(<McpServersPanel deps={deps} />);
    await waitFor(() => screen.getByTestId('mcp-servers-panel'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
