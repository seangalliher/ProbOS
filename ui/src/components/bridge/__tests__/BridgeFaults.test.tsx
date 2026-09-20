import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { spawn } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { delimiter, dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

import { BridgePanel } from '../../BridgePanel';
import { ApprovalsCenterPanel } from '../../approvals/ApprovalsCenterPanel';
import { useStore } from '../../../store/useStore';
import { validFaultDetail, validFaultList, type FaultDetailPayload, type FaultList } from '../../../hooks/useFaultReports';
import { RESOURCE_TIMEOUT_MS } from '../../../utils/resourceState';
import fixture from '../../../../e2e/fixtures/ad1207-faults.json';

const BASE = fixture.pending.list as FaultList;
const DETAIL = fixture.pending.detail as FaultDetailPayload;
const HEADLINE = BASE.faults[0].summary;
const rowButton = (): HTMLElement => screen.getByRole('button', { name: HEADLINE });
const refresh = (): void => { fireEvent.click(screen.getByRole('button', { name: 'Refresh fault reports' })); };
const tick = async (ms = 0): Promise<void> => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), { status });

function resetBridge(): void {
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources, approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null },
    approvalIssuedSeq: { capability: 0, skill: 0 }, approvalAppliedSeq: { capability: 0, skill: 0 },
    approvalRequestSeq: 0, capabilityDecisionRevision: 0, capabilityApprovalEpoch: 0, liveRepairEpoch: 0,
    decidedApprovals: new Set<string>(), pendingApprovals: [], approvalsCenterOpen: false,
    agentTasks: [], notifications: [], missionControlTasks: [], wardRoomDmChannels: [], wardRoomUnread: {},
  });
}

type Reply = (url: URL, init?: RequestInit) => Response | Promise<Response>;

function transport(faults: Reply) {
  const mock = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
    const url = new URL(String(input), 'http://test');
    if (url.pathname.startsWith('/api/faults')) return faults(url, init);
    if (url.pathname.startsWith('/api/capability-requests')) return json({ view: 'actionable', requests: [] });
    if (url.pathname.startsWith('/api/skill-requests')) return json({ requests: [] });
    return json([]);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function mount(open = true) {
  return render(<BridgePanel open={open} onClose={() => {}} />);
}

beforeEach(resetBridge);
afterEach(() => {
  cleanup();
  resetBridge();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-1207 actual Bridge fault consumer', () => {
  it('uses the current section, leads with behavior and renders safe accessible evidence', async () => {
    const user = userEvent.setup();
    transport(url => json(url.pathname === '/api/faults' ? fixture.filed.list : fixture.filed.detail));
    const view = mount();
    const button = await screen.findByRole('button', { name: HEADLINE });
    const section = screen.getByRole('button', { name: 'Faults (1)' }).parentElement!;
    expect(section.hasAttribute('data-station')).toBe(false);
    expect(section.hasAttribute('data-alerting')).toBe(false);
    expect(section.style.animation).toBe('');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    button.focus();
    await user.keyboard('{Enter}');
    const evidence = await screen.findByRole('region', { name: 'Fault evidence' });
    await within(evidence).findByText('counselor-ezri');
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(evidence).getByText('Recorded agent')).toBeVisible();
    expect(within(evidence).getByText('Stored trace sample')).toBeVisible();
    expect(view.container.querySelector('pre')).toHaveStyle({ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' });
    const link = screen.getByRole('link', { name: 'Issue owner/repo#37' });
    expect(link).toHaveAttribute('href', 'https://github.com/owner/repo/issues/37');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(button.contains(link)).toBe(false);
    button.focus();
    await user.tab();
    expect(link).toHaveFocus();
    expect(view.container.querySelector('[data-testid="bridge-faults"] svg')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByText(/affected agents/i)).toBeNull();
  });

  it('refreshes expanded receipts every 10 seconds without another occurrence', async () => {
    vi.useFakeTimers();
    let filed = false;
    const reads: string[] = [];
    transport(url => {
      reads.push(url.pathname);
      return json(url.pathname === '/api/faults' ? BASE : filed ? fixture.filed.detail : DETAIL);
    });
    mount();
    await tick();
    fireEvent.click(rowButton());
    await tick();
    expect(screen.getByText('No confirmed issue link.')).toBeVisible();
    filed = true;
    await tick(9_999);
    expect(screen.queryByRole('link', { name: 'Issue owner/repo#37' })).toBeNull();
    await tick(1);
    expect(screen.getByRole('link', { name: 'Issue owner/repo#37' })).toHaveAttribute('href', fixture.filed.detail.fault.issue.url);
    expect(reads.filter(path => path === `/api/faults/${BASE.faults[0].id}`)).toHaveLength(2);
    expect(screen.getByText('2', { selector: 'dd' })).toBeVisible();
  });

  it.each([503, 500, 401, 403])('does not call HTTP %s an empty fault collection', async status => {
    transport(() => json({ detail: 'do not expose server exception text' }, status));
    mount();
    const message = await screen.findByRole('status', { name: 'Fault reports status' });
    await waitFor(() => expect(message).toHaveTextContent(status === 401 || status === 403 ? 'Access denied' : status === 503 ? 'Unavailable' : 'Request failed'));
    expect(message).toHaveTextContent('Current count unknown');
    expect(screen.queryByText('No activity')).toBeNull();
    expect(message).not.toHaveTextContent('server exception');
  });

  it('keeps not-loaded and loading distinct from confirmed zero', async () => {
    let release!: (response: Response) => void;
    let calls = 0;
    transport(() => { calls += 1; return new Promise<Response>(accept => { release = accept; }); });
    const view = mount(false);
    expect(calls).toBe(0);
    expect(screen.getByRole('status', { name: 'Fault reports status' })).toHaveTextContent('Not requested');
    expect(screen.queryByText('No activity')).toBeNull();
    view.rerender(<BridgePanel open onClose={() => {}} />);
    await waitFor(() => expect(calls).toBe(1));
    expect(screen.getByRole('status', { name: 'Fault reports status' })).toHaveTextContent('Loading');
    await act(async () => { release(json(fixture.empty.list)); });
    await screen.findByText('No activity');
    expect(screen.queryByRole('button', { name: /^Faults \(/ })).toBeNull();
  });

  it('retains an explicit last-known count on failure, even when the last count was zero', async () => {
    vi.useFakeTimers();
    let state: 'empty' | 'failed' | 'populated' = 'empty';
    transport(() => state === 'failed' ? json({}, 503) : json(state === 'empty' ? fixture.empty.list : BASE));
    mount();
    await tick();
    expect(screen.getByText('No activity')).toBeVisible();
    state = 'failed';
    await tick(10_000);
    expect(screen.getByRole('button', { name: 'Faults (0 last-known; current unknown)' })).toBeVisible();
    expect(screen.queryByText('No activity')).toBeNull();
    state = 'populated';
    refresh();
    await tick();
    state = 'failed';
    await tick(10_000);
    expect(rowButton()).toBeVisible();
    expect(screen.getByRole('button', { name: 'Faults (1 last-known; current unknown)' })).toBeVisible();
  });

  it.each(['list', 'detail'])('purges all fault data after %s authorization failure and manually retries', async source => {
    vi.useFakeTimers();
    let denied = false;
    let calls = 0;
    transport(url => {
      calls += 1;
      const listing = url.pathname === '/api/faults';
      if (denied && listing === (source === 'list')) return json({}, 401);
      return json(listing ? fixture.filed.list : fixture.filed.detail);
    });
    mount();
    await tick();
    fireEvent.click(rowButton());
    await tick();
    denied = true;
    await tick(10_000);
    expect(screen.queryByRole('button', { name: HEADLINE })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Issue owner/repo#37' })).toBeNull();
    expect(screen.queryByText('counselor-ezri')).toBeNull();
    expect(screen.getByRole('status', { name: 'Fault reports status' })).toHaveTextContent('Access denied');
    const atDenial = calls;
    await tick(60_000);
    expect(calls).toBe(atDenial);
    denied = false;
    refresh();
    await tick();
    expect(rowButton()).toBeVisible();
  });

  it('uses the shared timeout, bounded backoff, pause and manual retry', async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    let recover = false;
    transport((_url, init) => {
      signals.push(init!.signal!);
      return recover ? json(BASE) : new Promise<Response>(() => {});
    });
    mount();
    await tick(RESOURCE_TIMEOUT_MS);
    expect(signals[0].aborted).toBe(true);
    expect(screen.getByRole('status', { name: 'Fault reports status' })).toHaveTextContent('Unavailable');
    await tick(10_000 + RESOURCE_TIMEOUT_MS + 5_000 + RESOURCE_TIMEOUT_MS);
    expect(signals).toHaveLength(3);
    expect(screen.getByRole('status', { name: 'Fault reports status' })).toHaveTextContent('Automatic refresh paused');
    await tick(60_000);
    expect(signals).toHaveLength(3);
    recover = true;
    refresh();
    await tick();
    expect(rowButton()).toBeVisible();
  });

  it('aborts requests and timers on close/unmount and refreshes on reopening', async () => {
    vi.useFakeTimers();
    let hold = true;
    const signals: AbortSignal[] = [];
    transport((_url, init) => {
      signals.push(init!.signal!);
      return hold ? new Promise<Response>(() => {}) : json(BASE);
    });
    const view = mount();
    await tick();
    view.rerender(<BridgePanel open={false} onClose={() => {}} />);
    expect(signals[0].aborted).toBe(true);
    await tick(60_000);
    expect(signals).toHaveLength(1);
    hold = false;
    view.rerender(<BridgePanel open onClose={() => {}} />);
    await tick();
    expect(rowButton()).toBeVisible();
    hold = true;
    refresh();
    await tick();
    view.unmount();
    expect(signals[signals.length - 1].aborted).toBe(true);
    const stopped = signals.length;
    await tick(60_000);
    expect(signals).toHaveLength(stopped);
  });

  it('ignores an obsolete list response after a replacement request', async () => {
    let release!: (response: Response) => void;
    let count = 0;
    let oldSignal!: AbortSignal;
    transport((_url, init) => {
      if (++count === 1) {
        oldSignal = init!.signal!;
        return new Promise<Response>(accept => { release = accept; });
      }
      return json(BASE);
    });
    mount();
    await waitFor(() => expect(count).toBe(1));
    refresh();
    await screen.findByRole('button', { name: HEADLINE });
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { release(json(fixture.empty.list)); });
    expect(rowButton()).toBeVisible();
    expect(screen.queryByText('No activity')).toBeNull();
  });

  it('rejects late detail from a previous selection and clears detail on removal', async () => {
    const second = { ...BASE.faults[0], id: '000000000003', summary: 'Another behavior failed' };
    let removed = false;
    let release!: (response: Response) => void;
    let oldSignal!: AbortSignal;
    transport((url, init) => {
      if (url.pathname === '/api/faults') return json(removed ? fixture.empty.list : { ...BASE, faults: [...BASE.faults, second], total: 2 });
      if (url.pathname.endsWith(second.id)) return json({ fault: { ...DETAIL.fault, ...second, recorded_agent_id: 'second-reporter' } });
      oldSignal = init!.signal!;
      return new Promise<Response>(accept => { release = accept; });
    });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: HEADLINE }));
    await waitFor(() => expect(oldSignal).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: second.summary }));
    await screen.findByText('second-reporter');
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { release(json(DETAIL)); });
    expect(screen.queryByText('counselor-ezri')).toBeNull();
    removed = true;
    refresh();
    await screen.findByText('No activity');
    expect(screen.queryByRole('region', { name: 'Fault evidence' })).toBeNull();
  });

  it('exposes remaining pages and corrects an empty out-of-range page without declaring global empty', async () => {
    const rows = Array.from({ length: 51 }, (_, index) => ({
      ...BASE.faults[0], id: (index + 1).toString(16).padStart(12, '0'), summary: `Behavior failure ${index + 1}`,
    }));
    let shrunk = false;
    const offsets: number[] = [];
    transport(url => {
      const offset = Number(url.searchParams.get('offset'));
      offsets.push(offset);
      const records = shrunk ? rows.slice(0, 1) : rows;
      return json({ faults: records.slice(offset, offset + 50), total: records.length, limit: 50, offset });
    });
    mount();
    await screen.findByRole('button', { name: 'Behavior failure 1' });
    expect(screen.getByRole('button', { name: 'Previous faults' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Next faults' }));
    await screen.findByRole('button', { name: 'Behavior failure 51' });
    expect(screen.getByText('51–51 of 51')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Next faults' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Previous faults' }));
    await screen.findByRole('button', { name: 'Behavior failure 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Next faults' }));
    await screen.findByRole('button', { name: 'Behavior failure 51' });
    shrunk = true;
    refresh();
    await screen.findByRole('button', { name: 'Behavior failure 1' });
    expect(offsets.slice(-2)).toEqual([50, 0]);
    expect(screen.queryByText('No activity')).toBeNull();
    expect(screen.getByRole('button', { name: 'Faults (1)' })).toBeVisible();
  });

  it('renders diagnostic markup as text and keeps int64 occurrences exact', async () => {
    const summary = '<img src=x onerror=alert(1)> failed to open';
    const detail = { fault: { ...DETAIL.fault, summary, occurrences: '9223372036854775807', error_text: '<script>bad()</script>' } };
    transport(url => json(url.pathname === '/api/faults'
      ? { ...BASE, faults: [{ ...BASE.faults[0], summary, occurrences: detail.fault.occurrences }] } : detail));
    const view = mount();
    fireEvent.click(await screen.findByRole('button', { name: summary }));
    await screen.findByText('9223372036854775807', { selector: 'dd' });
    expect(screen.getByText('<script>bad()</script>')).toBeVisible();
    expect(view.container.querySelector('article img, article script')).toBeNull();
  });

  it('keeps unavailable receipt lookup and unavailable evidence visible', async () => {
    const fault = { ...DETAIL.fault, issue_lookup_available: false, trace_available: false, trace_summary: 'Stored trace sample unavailable.' };
    transport(url => json(url.pathname === '/api/faults' ? { ...BASE, faults: [{ ...BASE.faults[0], issue_lookup_available: false }] } : { fault }));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: HEADLINE }));
    await screen.findByText('Stored trace sample unavailable.');
    expect(screen.getByText('Issue link lookup unavailable.')).toBeVisible();
    expect(screen.queryByText('No confirmed issue link.')).toBeNull();
  });
});

describe('AD-1207 matching wire guards at the real hook boundary', () => {
  it.each([
    null, [], { faults: [] }, { ...BASE, total: 0 }, { ...BASE, limit: 101 },
    { ...BASE, offset: -1 }, { ...BASE, total: 9007199254740992 },
    { ...BASE, faults: [...BASE.faults, ...BASE.faults], total: 2 },
    ...[0, '0', '01', '9223372036854775808', '-1', '1.5'].map(occurrences => ({
      ...BASE, faults: [{ ...BASE.faults[0], occurrences }],
    })),
    ...[
      { id: 'BAD' }, { status: 'repaired' }, { signature: 'bad' },
      { issue: { repository: 'owner/repo', number: 37, url: 'javascript:alert(1)' } },
      { issue: { repository: 'owner/repo', number: 37, url: 'https://github.com/other/repo/issues/37' } },
    ].map(change => ({ ...BASE, faults: [{ ...BASE.faults[0], ...change }] })),
  ])('rejects malformed list payload %# without treating it as empty', async payload => {
    expect(validFaultList(payload)).toBe(false);
    transport(() => json(payload));
    mount();
    await waitFor(() => expect(screen.getByRole('status', { name: 'Fault reports status' })).toHaveTextContent('Request failed'));
    expect(screen.queryByText('No activity')).toBeNull();
  });

  it.each([
    null, {}, { fault: BASE.faults[0] },
    { fault: { ...DETAIL.fault, error_text: 'x'.repeat(2001) } },
    { fault: { ...DETAIL.fault, trace_summary: 'x'.repeat(4001) } },
    { fault: { ...DETAIL.fault, clipped_fields: ['invented'] } },
  ])('rejects malformed detail payload %# through the actual consumer', async payload => {
    expect(validFaultDetail(payload)).toBe(false);
    transport(url => json(url.pathname === '/api/faults' ? BASE : payload));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: HEADLINE }));
    await waitFor(() => expect(screen.getByRole('status', { name: 'Fault detail status' })).toHaveTextContent('Request failed'));
    expect(screen.queryByText('counselor-ezri')).toBeNull();
  });

  it('accepts actual empty/detail contracts and refuses a wrong detail identity', async () => {
    expect(validFaultList(fixture.empty.list)).toBe(true);
    expect(validFaultDetail(DETAIL)).toBe(true);
    expect(validFaultDetail({ fault: { ...DETAIL.fault, error_text: '\u{10400}'.repeat(2000) } })).toBe(true);
    transport(url => json(url.pathname === '/api/faults' ? BASE : fixture.recurrence.detail));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: HEADLINE }));
    await waitFor(() => expect(screen.getByRole('status', { name: 'Fault detail status' })).toHaveTextContent('Request failed'));
    expect(screen.queryByText('counselor-ezri')).toBeNull();
  });
});

interface Backend {
  send: <T = unknown>(command: Record<string, unknown>) => Promise<T>;
  stop: () => Promise<void>;
}

function requiredPython(root: string, override = process.env.PROBOS_TEST_PYTHON): string {
  const executable = override ?? (process.platform === 'win32'
    ? 'D:\\ProbOS\\.venv\\Scripts\\python.exe' : join(root, '.venv/bin/python'));
  if (!executable || !existsSync(executable) || !statSync(executable).isFile()) {
    throw new Error('Approved backend interpreter missing; set PROBOS_TEST_PYTHON. This crossing must not skip.');
  }
  return executable;
}

async function startBackend(): Promise<Backend> {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..');
  const executable = requiredPython(root);
  const ownedRoot = await mkdtemp(join(tmpdir(), 'probos-ad1207-owned-'));
  const child = spawn(executable, ['-u', '-c',
    'import asyncio, sys; from tests.test_ad1207_fault_visibility import _serve_bridge; asyncio.run(_serve_bridge(sys.argv[1]))',
    ownedRoot,
  ], {
    cwd: root, shell: false, windowsHide: true,
    env: {
      ...process.env, PYTHONPATH: [join(root, 'src'), root].join(delimiter),
      PYTHONDONTWRITEBYTECODE: '1', PROBOS_NATS_ENABLED: 'false', HF_HUB_OFFLINE: '1',
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let sequence = 0;
  let diagnostics = '';
  const pending = new Map<number, { accept: (value: unknown) => void; reject: (error: Error) => void }>();
  const lines = createInterface({ input: child.stdout });
  const rejectAll = (error: Error): void => {
    for (const waiter of pending.values()) waiter.reject(error);
    pending.clear();
  };
  child.stderr.on('data', chunk => { diagnostics = (diagnostics + String(chunk)).slice(-12000); });
  child.on('error', rejectAll);
  child.stdin.on('error', rejectAll);
  lines.on('line', line => {
    try {
      const payload = JSON.parse(line) as { id: number; result: unknown };
      const waiter = pending.get(payload.id);
      if (!waiter) throw new Error('Unexpected backend response identity');
      pending.delete(payload.id);
      waiter.accept(payload.result);
    } catch {
      rejectAll(new Error(`Invalid backend protocol: ${line.slice(0, 500)}`));
      child.kill();
    }
  });
  const exited = new Promise<number | null>(accept => {
    child.on('close', code => {
      rejectAll(new Error(`Owned backend exited ${code}: ${diagnostics}`));
      accept(code);
    });
  });
  const backend: Backend = {
    send: <T,>(command: Record<string, unknown>): Promise<T> => new Promise<T>((accept, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`Owned backend command timed out: ${diagnostics}`));
        child.kill();
      }, 25_000);
      pending.set(id, {
        accept: value => { clearTimeout(timer); accept(value as T); },
        reject: error => { clearTimeout(timer); reject(error); },
      });
      child.stdin.write(JSON.stringify({ id, ...command }) + '\n');
    }),
    stop: async (): Promise<void> => {
      child.stdin.end();
      const timer = setTimeout(() => { child.kill(); }, 5_000);
      try {
        const code = await exited;
        if (code !== 0) throw new Error(`Owned Python cleanup failed (${child.pid}, ${code}): ${diagnostics}`);
      } finally {
        clearTimeout(timer);
        lines.close();
        await rm(ownedRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
        expect(existsSync(ownedRoot)).toBe(false);
      }
    },
  };
  try {
    const hello = await backend.send<{
      root: string; python: string; api: string; owned_store_root: string;
      historical_fixture_not_launch_evidence: boolean;
    }>({ action: 'hello' });
    expect(resolve(hello.root)).toBe(root);
    expect(resolve(hello.python)).toBe(resolve(executable));
    expect(resolve(hello.api)).toBe(join(root, 'src/probos/api.py'));
    expect(resolve(hello.owned_store_root)).toBe(resolve(ownedRoot));
    expect(hello.historical_fixture_not_launch_evidence).toBe(true);
    return backend;
  } catch (error) {
    await backend.stop();
    throw error;
  }
}

it('fails rather than skips when the approved Python interpreter is missing', () => {
  expect(() => requiredPython('.', '')).toThrow('must not skip');
});

it('crosses one live test session: historical loop/trace → Bridge → real approval → receipt → restart/recurrence', async () => {
  const backend = await startBackend();
  const control = async (command: Record<string, unknown>): Promise<unknown> => {
    let result: unknown;
    await act(async () => { result = await backend.send(command); });
    return result;
  };
  try {
    expect(await control({ action: 'observe', turns: 2 })).toEqual([
      { turn: 1, total: 0, occurrences: null, approvals: 0 },
      { turn: 2, total: 0, occurrences: null, approvals: 0 },
    ]);
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.startsWith('/api/faults') || path.startsWith('/api/capability-requests')) {
        const response = await backend.send<{ status: number; body: unknown }>({
          action: 'request', path, method: init?.method ?? 'GET',
          body: init?.body ? JSON.parse(String(init.body)) : null,
        });
        return json(response.body, response.status);
      }
      return json(path.startsWith('/api/skill-requests') ? { requests: [] } : []);
    });
    vi.stubGlobal('fetch', fetchMock);
    const element = (open: boolean): React.ReactNode => <><BridgePanel open={open} onClose={() => {}} /><ApprovalsCenterPanel /></>;
    const view = render(element(true));
    await screen.findByText('No activity');
    expect(await control({ action: 'snapshot' })).toEqual(fixture.empty);
    expect(await control({ action: 'observe', turns: 1 })).toEqual([{ turn: 3, total: 1, occurrences: 1, approvals: 0 }]);
    view.rerender(element(false));
    view.rerender(element(true));
    fireEvent.click(await screen.findByRole('button', { name: HEADLINE }));
    await screen.findByText('1', { selector: 'dd' });
    expect(await control({ action: 'observe', turns: 1 })).toEqual([{ turn: 4, total: 1, occurrences: 2, approvals: 1 }]);
    refresh();
    await act(async () => { await useStore.getState().refreshPendingApprovals(); });
    await screen.findByText('2', { selector: 'dd' });
    expect(await control({ action: 'snapshot' })).toEqual(fixture.pending);

    const approvalHeader = screen.getByRole('button', { name: /^Approvals \(1\)/ });
    const faultHeader = screen.getByRole('button', { name: 'Faults (1)' });
    expect(approvalHeader.compareDocumentPosition(faultHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(approvalHeader.parentElement).toHaveAttribute('data-alerting', 'true');
    const station = view.container.querySelector('[data-station]')!;
    expect(faultHeader.compareDocumentPosition(station) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(faultHeader.parentElement).not.toHaveAttribute('data-alerting');

    fireEvent.click(screen.getByTestId('bridge-approval-row'));
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(useStore.getState().pendingApprovals).toHaveLength(0));
    refresh();
    const link = await screen.findByRole('link', { name: 'Issue owner/repo#37' });
    expect(link).toHaveAttribute('href', fixture.filed.detail.fault.issue.url);
    expect(await control({ action: 'snapshot' })).toEqual(fixture.filed);
    expect(await control({ action: 'restart' })).toEqual(fixture.filed);
    refresh();
    await waitFor(() => expect(screen.getByRole('status', { name: 'Fault reports status' })).not.toHaveTextContent('Refreshing'));
    expect(await control({ action: 'close' })).toEqual(fixture.empty);
    refresh();
    await screen.findByText('No activity');
    expect(screen.queryByRole('region', { name: 'Fault evidence' })).toBeNull();
    expect(await control({ action: 'observe', turns: 2 })).toEqual([
      { turn: 5, total: 0, occurrences: null, approvals: 0 },
      { turn: 6, total: 0, occurrences: null, approvals: 0 },
    ]);
    await control({ action: 'observe', turns: 1 });
    view.rerender(element(false));
    view.rerender(element(true));
    const recurrence = await screen.findByRole('button', { name: HEADLINE });
    expect(recurrence).toHaveAttribute('aria-expanded', 'false');
    expect(recurrence.closest('article')).toHaveAttribute('data-fault-id', '000000000002');
    fireEvent.click(recurrence);
    await screen.findByText('1', { selector: 'dd' });
    await control({ action: 'observe', turns: 1 });
    refresh();
    await act(async () => { await useStore.getState().refreshPendingApprovals(); });
    await screen.findByText('2', { selector: 'dd' });
    fireEvent.click(screen.getByTestId('bridge-approval-row'));
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(useStore.getState().pendingApprovals).toHaveLength(0));
    expect(await control({ action: 'snapshot' })).toEqual(fixture.recurrence);
    expect(await control({ action: 'evidence' })).toMatchObject({
      posts: 1, http_calls: 1, credential_calls: 1, internal_repairs: 0, sandbox_calls: 8,
    });
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/faults?limit=50&offset=0')).toBe(true);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2);
    view.unmount();
  } finally {
    cleanup();
    await backend.stop();
  }
}, 60_000);
