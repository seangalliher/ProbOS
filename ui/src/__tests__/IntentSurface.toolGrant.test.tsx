/** AD-720b: IntentSurface /grant slash-command tests. */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

function makeAgent(id: string, callsign: string) {
  return {
    id,
    agentType: callsign.toLowerCase(),
    callsign,
    displayName: `${callsign} role`,
    pool: callsign.toLowerCase(),
    state: 'active' as const,
    confidence: 0.8,
    trust: 0.7,
    tier: 'domain' as const,
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: 'engineering',
  };
}

beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map([['e1', makeAgent('e1', 'echo')]]),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openShell() {
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

function getInput(): HTMLInputElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount');
  return input;
}

function getForm(input: HTMLInputElement): HTMLFormElement {
  const form = input.closest('form');
  if (!form) throw new Error('Form not found');
  return form;
}

describe('AD-720b IntentSurface /grant slash-command', () => {
  it('typing "/grant e1 BrowserTool read 2" POSTs tool-grant with duration_hours=2', async () => {
    let captured: any = null;
    global.fetch = vi.fn().mockImplementation((url: any, init?: any) => {
      if (String(url) === '/api/chat/tool-grant') {
        captured = JSON.parse(init.body);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            grant_id: 'g1',
            agent_id: 'e1',
            tool_id: 'BrowserTool',
            permission: 'read',
            expires_at: Date.now() / 1000 + 7200,
            issued_at: Date.now() / 1000,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as any;

    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '/grant e1 BrowserTool read 2' } });
    fireEvent.submit(getForm(input));

    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
    expect(captured).not.toBeNull();
    expect(captured.agent_id).toBe('e1');
    expect(captured.tool_id).toBe('BrowserTool');
    expect(captured.permission).toBe('read');
    expect(captured.duration_hours).toBe(2);
  });

  it('typing "/grant e1 BrowserTool read" (no hours) POSTs duration_hours=null', async () => {
    let captured: any = null;
    global.fetch = vi.fn().mockImplementation((url: any, init?: any) => {
      if (String(url) === '/api/chat/tool-grant') {
        captured = JSON.parse(init.body);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            grant_id: 'g1', agent_id: 'e1', tool_id: 'BrowserTool',
            permission: 'read', expires_at: null, issued_at: Date.now() / 1000,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as any;

    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '/grant e1 BrowserTool read' } });
    fireEvent.submit(getForm(input));

    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
    expect(captured).not.toBeNull();
    expect(captured.duration_hours).toBeNull();
  });

  it('422 response preserves the typed text in the composer', async () => {
    global.fetch = vi.fn().mockImplementation((url: any) => {
      if (String(url) === '/api/chat/tool-grant') {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: () => Promise.resolve({ detail: { reason: 'invalid_permission' } }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as any;

    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '/grant e1 BrowserTool rwx' } });
    fireEvent.submit(getForm(input));

    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
    // After rejection the input is restored.
    expect(getInput().value).toBe('/grant e1 BrowserTool rwx');
    const hist = useStore.getState().chatHistory;
    const sys = hist.find((m) => m.role === 'system' && /rejected/.test(m.text));
    expect(sys).toBeDefined();
  });

  it('successful POST renders a system-styled inline message', async () => {
    global.fetch = vi.fn().mockImplementation((url: any) => {
      if (String(url) === '/api/chat/tool-grant') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            grant_id: 'g1', agent_id: 'e1', tool_id: 'BrowserTool',
            permission: 'read', expires_at: Date.now() / 1000 + 7200,
            issued_at: Date.now() / 1000,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as any;

    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '/grant e1 BrowserTool read 2' } });
    fireEvent.submit(getForm(input));

    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
    const hist = useStore.getState().chatHistory;
    const sys = hist.find((m) => m.role === 'system' && /Granted BrowserTool read to e1/.test(m.text));
    expect(sys).toBeDefined();
  });
});
