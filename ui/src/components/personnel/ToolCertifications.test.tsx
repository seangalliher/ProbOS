/** AD-899 (Wave 258) vitest — Tool certification management view.
 * The asset/certification surface for AD-894: browse the ship tool catalog,
 * select a crew agent, view their active certifications, grant a qualification,
 * and revoke one behind a two-step confirm. Upholds the HXI no-emoji guard. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import ToolCertifications from './ToolCertifications';

interface Call {
  url: string;
  method: string;
  body: any;
}

const CATALOG = [
  {
    tool_id: 'tool-shell',
    name: 'Shell Executor',
    tool_type: 'deterministic_function',
    description: 'Run shell commands.',
    domain: 'engineering',
    department: 'engineering',
    enabled: true,
  },
  {
    tool_id: 'tool-http',
    name: 'HTTP Fetch',
    tool_type: 'remote_api',
    description: 'Fetch remote resources.',
    domain: '*',
    department: 'science',
    enabled: true,
  },
];

const ROSTER = [
  { agent_id: 'agent-1', callsign: 'Data', post: 'Operations', department: 'engineering' },
];

const CERTS = [
  {
    grant_id: 'grant-1',
    tool_id: 'tool-shell',
    permission: 'write',
    is_restriction: false,
    reason: 'Engineering duty.',
    issued_by: 'captain',
  },
];

function stubFetch(calls: Call[], opts?: { revokeStatus?: number; revokeDetail?: string }) {
  global.fetch = vi.fn((url: string, init?: any) => {
    const method = (init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(init.body) : null;
    calls.push({ url, method, body });
    if (method === 'GET') {
      if (url.startsWith('/api/tools')) {
        return Promise.resolve({ ok: true, json: async () => ({ tools: CATALOG, count: CATALOG.length }) }) as any;
      }
      if (url.startsWith('/api/crew/roster')) {
        return Promise.resolve({ ok: true, json: async () => ({ crew: ROSTER, count: ROSTER.length }) }) as any;
      }
      // /api/crew/{id}/tools
      return Promise.resolve({
        ok: true,
        json: async () => ({ agent_id: 'agent-1', certifications: CERTS, count: CERTS.length }),
      }) as any;
    }
    if (method === 'DELETE' && opts?.revokeStatus && opts.revokeStatus >= 400) {
      return Promise.resolve({
        ok: false,
        status: opts.revokeStatus,
        json: async () => ({ detail: opts.revokeDetail || 'rejected' }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  }) as any;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ToolCertifications (AD-899)', () => {
  let calls: Call[];
  beforeEach(() => {
    calls = [];
  });

  it('1. renders the tool catalog from GET /api/tools', async () => {
    stubFetch(calls);
    render(<ToolCertifications />);
    await waitFor(() => {
      expect(calls.some(c => c.method === 'GET' && c.url.startsWith('/api/tools'))).toBe(true);
    });
    // Catalog options appear in the grant tool selector.
    expect(await screen.findByText('Shell Executor')).toBeTruthy();
    expect(screen.getByText('HTTP Fetch')).toBeTruthy();
  });

  it('2. grant adds a certification via POST /api/crew/{id}/tools', async () => {
    stubFetch(calls);
    render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    // Select the crew member, then the tool, then certify.
    fireEvent.change(screen.getByTestId('tool-agent-select'), { target: { value: 'agent-1' } });
    fireEvent.change(screen.getByTestId('tool-grant-tool'), { target: { value: 'tool-http' } });
    fireEvent.change(screen.getByTestId('tool-grant-permission'), { target: { value: 'read' } });
    fireEvent.click(screen.getByTestId('tool-grant-submit'));
    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST');
      expect(post).toBeTruthy();
      expect(post!.url).toBe('/api/crew/agent-1/tools');
      expect(post!.body.tool_id).toBe('tool-http');
      expect(post!.body.permission).toBe('read');
    });
  });

  it('3. grant validates a missing tool before POSTing', async () => {
    stubFetch(calls);
    render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    fireEvent.change(screen.getByTestId('tool-agent-select'), { target: { value: 'agent-1' } });
    // No tool selected → inline validation, no POST.
    fireEvent.click(screen.getByTestId('tool-grant-submit'));
    expect(screen.getByTestId('tool-grant-error').textContent).toContain('Tool is required');
    expect(calls.some(c => c.method === 'POST')).toBe(false);
  });

  it('4. revoke requires a two-step confirm before DELETE', async () => {
    stubFetch(calls);
    render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    fireEvent.change(screen.getByTestId('tool-agent-select'), { target: { value: 'agent-1' } });
    await screen.findByTestId('tool-cert-grant-1');
    fireEvent.click(screen.getByTestId('tool-revoke-grant-1'));
    // No DELETE yet — only the confirm button appears.
    expect(calls.some(c => c.method === 'DELETE')).toBe(false);
    fireEvent.click(screen.getByTestId('tool-revoke-confirm-grant-1'));
    await waitFor(() => {
      const del = calls.find(c => c.method === 'DELETE');
      expect(del).toBeTruthy();
      expect(del!.url).toBe('/api/crew/agent-1/tools/grant-1');
    });
  });

  it('5. a rejected revoke surfaces the server error inline', async () => {
    stubFetch(calls, { revokeStatus: 400, revokeDetail: 'Grant is locked by an active assignment.' });
    render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    fireEvent.change(screen.getByTestId('tool-agent-select'), { target: { value: 'agent-1' } });
    await screen.findByTestId('tool-cert-grant-1');
    fireEvent.click(screen.getByTestId('tool-revoke-grant-1'));
    fireEvent.click(screen.getByTestId('tool-revoke-confirm-grant-1'));
    await waitFor(() => {
      expect(screen.getByTestId('tool-row-error').textContent).toContain('locked');
    });
  });

  it('6. renders no emoji (HXI Principle #3)', async () => {
    stubFetch(calls);
    const { container } = render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    expect(/\p{Extended_Pictographic}/u.test(container.textContent || '')).toBe(false);
  });

  it('7. Restrict mode POSTs is_restriction=true with permission none (AD-909a)', async () => {
    stubFetch(calls);
    render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    fireEvent.change(screen.getByTestId('tool-agent-select'), { target: { value: 'agent-1' } });
    fireEvent.change(screen.getByTestId('tool-grant-tool'), { target: { value: 'tool-http' } });
    // Switch to Restrict mode — the permission selector becomes a "blocked" note.
    fireEvent.click(screen.getByTestId('tool-mode-restrict'));
    expect(screen.getByTestId('tool-restrict-note').textContent).toContain('blocked');
    expect(screen.getByTestId('tool-grant-submit').textContent).toContain('Restrict');
    fireEvent.click(screen.getByTestId('tool-grant-submit'));
    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST');
      expect(post).toBeTruthy();
      expect(post!.body.tool_id).toBe('tool-http');
      expect(post!.body.is_restriction).toBe(true);
      expect(post!.body.permission).toBe('none');
    });
  });

  it('8. Grant mode (default) POSTs is_restriction=false (AD-909a)', async () => {
    stubFetch(calls);
    render(<ToolCertifications />);
    await screen.findByText('Shell Executor');
    fireEvent.change(screen.getByTestId('tool-agent-select'), { target: { value: 'agent-1' } });
    fireEvent.change(screen.getByTestId('tool-grant-tool'), { target: { value: 'tool-http' } });
    fireEvent.click(screen.getByTestId('tool-grant-submit'));
    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST');
      expect(post!.body.is_restriction).toBe(false);
    });
  });
});
