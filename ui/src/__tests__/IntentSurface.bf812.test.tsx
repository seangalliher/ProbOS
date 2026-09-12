/** BF-812: IntentSurface must show an AD-698 policy refusal as policy state.
 *
 *  The chat POST chain was `.then((res) => res.json())` with no `res.ok`
 *  check, so a 403 refusal body fell through every branch to the final
 *  `'(No response)'` fallback. That tells the Captain the agent had nothing to
 *  say — a refusal wearing an outage costume.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act, fireEvent, waitFor } from '@testing-library/react';
import { execFile } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';
import { speakResponse } from '../audio/voice';

vi.mock('../audio/voice', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../audio/voice')>();
  return { ...actual, speakResponse: vi.fn() };
});

interface CalculatorRequest {
  message: string;
  history: Array<{ role: string; text: string }>;
  attachment_ids: string[];
}

interface CalculatorPair {
  request: CalculatorRequest;
  envelope: {
    response: string;
    dag: { source_text: string; reflect: boolean };
    results: Record<string, { result_count: number; results: Array<{ agent_id: string }> }>;
  };
}

const repeatedCommand = 'calculate 17 multiplied by 23 and return only the answer';
const calculatorRequests: CalculatorRequest[] = [
  repeatedCommand,
  repeatedCommand,
  'calculate 11 multiplied by 13 and return only the answer',
  'calculate 17 multiplied by 23 twice as separate tasks',
  repeatedCommand,
].map((message, index) => ({
  message,
  history: index === 1
    ? [{ role: 'user', text: repeatedCommand }, { role: 'system', text: '391' }]
    : [],
  attachment_ids: [],
}));

async function resolveCalculatorPython(
  root: string,
  overrides: { PROBOS_TEST_PYTHON?: string; PROBOS_PYTHON?: string } = process.env,
): Promise<string> {
  const isFile = (candidate: string): boolean => existsSync(candidate) && statSync(candidate).isFile();
  for (const name of ['PROBOS_TEST_PYTHON', 'PROBOS_PYTHON'] as const) {
    if (overrides[name] === undefined) continue;
    const candidate = resolve(root, overrides[name]);
    if (!overrides[name] || !isFile(candidate)) {
      throw new Error(`${name} must name an existing Python executable: ${candidate}`);
    }
    return realpath(candidate);
  }
  const candidates = ['.venv/Scripts/python.exe', '.venv/bin/python'].map((relative) => join(root, relative));
  const local = candidates.find(isFile);
  if (local) return realpath(local);
  let commonDirectory: string;
  try {
    const output = await new Promise<string>((accept, reject) => {
      execFile('git', ['-C', root, 'rev-parse', '--git-common-dir'], {
        shell: false, timeout: 5_000, maxBuffer: 65_536, encoding: 'utf8',
      }, (error, stdout) => error ? reject(error) : accept(stdout.trim()));
    });
    if (!output) throw new Error('Git returned an empty common directory');
    commonDirectory = await realpath(resolve(root, output));
  } catch (error) {
    throw Object.assign(new Error(
      'Cannot resolve the backend test environment. Set PROBOS_TEST_PYTHON or PROBOS_PYTHON, '
      + 'or run uv sync --group dev --extra discovery --extra browser in the repository.',
    ), { cause: error });
  }
  candidates.push(...['.venv/Scripts/python.exe', '.venv/bin/python']
    .map((relative) => join(dirname(commonDirectory), relative)));
  const common = candidates.find(isFile);
  if (common) return realpath(common);
  throw new Error(
    'No backend test interpreter found. Set PROBOS_TEST_PYTHON or PROBOS_PYTHON, '
    + 'or run uv sync --group dev --extra discovery --extra browser. Checked: '
    + candidates.join(', '),
  );
}

async function cleanupCalculatorDirectory(
  temporary: string, originalError: unknown, remove: typeof rm = rm,
): Promise<void> {
  try {
    await remove(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  } catch (cleanupError) {
    if (originalError !== undefined) {
      throw Object.assign(new Error('Calculator execution and cleanup failed'), {
        errors: [originalError, cleanupError], cause: originalError,
      });
    }
    throw cleanupError;
  }
  if (originalError !== undefined) throw originalError;
}

function parseCalculatorBatch(stdout: string, context: string): { pairs: CalculatorPair[] } {
  try {
    return JSON.parse(stdout) as { pairs: CalculatorPair[] };
  } catch (error) {
    throw Object.assign(new Error(`Calculator API fixture returned invalid JSON. ${context}`), { cause: error });
  }
}

async function loadCalculatorPairs(): Promise<CalculatorPair[]> {
  const started = Date.now();
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
  const python = await resolveCalculatorPython(root);
  const input = JSON.stringify(calculatorRequests);
  if (Buffer.byteLength(input) > 65_536) throw new Error('Calculator request batch is too large');
  const temporary = await mkdtemp(join(tmpdir(), 'probos-calculator-test-'));
  let pairs: CalculatorPair[] | undefined;
  let setupError: unknown;
  try {
    const remaining = 50_000 - (Date.now() - started);
    if (remaining <= 0) throw new Error('Calculator setup exhausted its child-work budget');
    const script = [
      'import json, os, runpy, sys',
      "with os.fdopen(os.dup(1), 'w', encoding='utf-8') as protocol:",
      '    os.dup2(2, 1)',
      "    os.write(1, b'issue1378-native-stdout-check\\n')",
      "    module = runpy.run_path('tests/test_hxi_chat_integration.py', run_name='probos_test_bridge')",
      "    batch = module['_calculator_bridge']()",
      '    json.dump(batch, protocol)',
      '    protocol.flush()',
    ].join('\n');
    const output = await new Promise<{ stdout: string; context: string; stderr: string }>((accept, reject) => {
      let inputFailure: Error | undefined;
      const child = execFile(python, ['-c', script], {
        cwd: root,
        shell: false,
        timeout: remaining,
        killSignal: 'SIGKILL',
        maxBuffer: 1_048_576,
        encoding: 'utf8',
        env: {
          ...process.env,
          PYTHONPATH: join(root, 'src'),
          PROBOS_DATA_DIR: temporary,
          PROBOS_EMBEDDINGS: 'local',
          PROBOS_NATS_ENABLED: 'false',
          HF_HUB_OFFLINE: '1',
        },
      }, (error, output, stderr) => {
        const context = `${python}, ${Date.now() - started}ms, exit=${error?.code ?? 0}, `
          + `signal=${error?.signal ?? 'none'}\n${stderr}`;
        if (error || inputFailure) {
          reject(new Error(`Calculator API fixture failed: ${inputFailure ?? error}\n${context}`));
        } else {
          accept({ stdout: output, context, stderr });
        }
      });
      child.stdin?.once('error', (error: Error) => {
        inputFailure = error;
        child.kill('SIGKILL');
      });
      child.stdin?.end(input);
    });
    expect(output.stderr).toContain('issue1378-native-stdout-check');
    expect(output.stdout).not.toContain('issue1378-native-stdout-check');
    const batch = parseCalculatorBatch(output.stdout, output.context);
    expect(Object.keys(batch)).toEqual(['pairs']);
    expect(batch.pairs).toHaveLength(5);
    expect(batch.pairs.map((pair) => pair.request)).toEqual(calculatorRequests);
    expect(batch.pairs.map((pair) => pair.envelope.response)).toEqual([
      '391', '391', '143', '391\n391', '391',
    ]);
    for (const [index, pair] of batch.pairs.entries()) {
      expect(pair.envelope.dag).toEqual({ source_text: pair.request.message, reflect: false });
      const nodes = Object.values(pair.envelope.results);
      expect(nodes).toHaveLength(index === 3 ? 2 : 1);
      for (const node of nodes) {
        expect(node.results.length).toBeGreaterThanOrEqual(2);
        expect(node.result_count).toBe(node.results.length);
        expect(new Set(node.results.map((result) => result.agent_id)).size).toBe(node.result_count);
      }
    }
    pairs = batch.pairs;
  } catch (error) {
    setupError = error;
  }
  await cleanupCalculatorDirectory(temporary, setupError);
  if (!pairs) throw new Error('Calculator setup completed without its required batch');
  expect(existsSync(temporary)).toBe(false);
  const elapsedMs = Date.now() - started;
  if (elapsedMs >= 60_000) throw new Error(`Calculator fixture setup exceeded its budget: ${elapsedMs}ms`);
  console.info('Issue 1378 API fixture setup', { elapsedMs, childExit: 0, pairs: pairs.length, cleanupVerified: true });
  return pairs;
}

const calculatorSetup = await loadCalculatorPairs().then(
  (pairs) => ({ pairs, error: undefined }),
  (error: unknown) => ({ pairs: [] as CalculatorPair[], error }),
);
const calculatorPairs = calculatorSetup.pairs;

function matchCalculatorPair(body: unknown, pair: CalculatorPair): CalculatorPair['envelope'] {
  expect(body).toEqual(pair.request);
  expect(pair.envelope.dag.source_text).toBe(pair.request.message);
  return pair.envelope;
}

function installCalculatorFetch(pairs: CalculatorPair[]): () => void {
  const original = structuredClone(pairs);
  let consumed = 0;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) !== '/api/chat') {
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }
    expect(init?.method).toBe('POST');
    expect(consumed).toBeLessThan(pairs.length);
    const envelope = matchCalculatorPair(JSON.parse(String(init?.body)), pairs[consumed]);
    consumed += 1;
    return { ok: true, status: 200, json: async () => envelope } as Response;
  }));
  return () => {
    expect(consumed).toBe(pairs.length);
    expect(pairs).toEqual(original);
  };
}

let chatBody: unknown = { response: 'ok' };
let chatStatus = 200;
let previousVoiceEnabled = false;

function installFetch(): void {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url === '/api/chat') {
      return Promise.resolve({
        ok: chatStatus >= 200 && chatStatus < 300,
        status: chatStatus,
        json: () => Promise.resolve(chatBody),
      } as Response);
    }
    return Promise.resolve({
      ok: true, status: 200, json: () => Promise.resolve({}),
    } as Response);
  }));
}

function openShell(): void {
  // The shell starts collapsed as a pill; clicking it mounts the input.
  const pillText = screen.queryByText(/Ask ProbOS/);
  const clickable = pillText?.closest('div');
  if (clickable) fireEvent.click(clickable);
}

async function ask(text = 'do the thing'): Promise<void> {
  openShell();
  // IntentSurface renders outside the RTL container, so query the document —
  // the same approach IntentSurface.atMention.test.tsx uses.
  const input = document.querySelector(
    'input[placeholder="Ask ProbOS..."]',
  ) as HTMLInputElement | null;
  if (input === null) throw new Error('chat input not rendered');
  fireEvent.change(input, { target: { value: text } });
  await act(async () => {
    fireEvent.submit(input.closest('form')!);
    await Promise.resolve();
  });
}

function chatTexts(): Array<{ role: string; text: string }> {
  return useStore.getState().chatHistory.map((m) => ({ role: m.role, text: m.text }));
}

beforeEach(() => {
  previousVoiceEnabled = useStore.getState().voiceEnabled;
  chatBody = { response: 'ok' };
  chatStatus = 200;
  installFetch();
  useStore.setState({ chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map(), voiceEnabled: false });
});

afterEach(() => {
  cleanup();
  useStore.setState({ voiceEnabled: previousVoiceEnabled, chatHistory: [], pendingRequests: 0 });
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('BF-812 IntentSurface renders a policy refusal as policy state', () => {
  it('names the refusal instead of falling through to "(No response)"', async () => {
    chatStatus = 403;
    chatBody = { error: 'intent_denied', reason: 'rbac' };
    render(<IntentSurface />);

    await ask();

    await waitFor(() => {
      expect(chatTexts().some((m) => m.text.includes('rbac'))).toBe(true);
    });
    const denial = chatTexts().find((m) => m.text.includes('rbac'));
    expect(denial?.role).toBe('system');
    expect(chatTexts().some((m) => m.text.includes('(No response)'))).toBe(false);
  });

  it('leaves an ordinary reply untouched', async () => {
    chatBody = { response: 'acknowledged' };
    render(<IntentSurface />);

    await ask();

    await waitFor(() => {
      expect(chatTexts().some((m) => m.text === 'acknowledged')).toBe(true);
    });
    expect(chatTexts().some((m) => m.text.toLowerCase().includes('policy refused')))
      .toBe(false);
  });
});

describe('Issue 1378 real API envelopes reach HXI history and narration', () => {
  beforeEach(() => {
    if (calculatorSetup.error) throw calculatorSetup.error;
    expect(calculatorPairs).toHaveLength(5);
  });

  it('keeps repeated requests as separate answers and utterances', async () => {
    const verify = installCalculatorFetch(calculatorPairs.slice(0, 2));
    useStore.setState({ voiceEnabled: true });
    render(<IntentSurface />);
    for (let occurrence = 1; occurrence <= 2; occurrence += 1) {
      await ask(repeatedCommand);
      await waitFor(() => {
        expect(chatTexts().filter((message) => message.role === 'system')).toHaveLength(occurrence);
        expect(vi.mocked(speakResponse)).toHaveBeenCalledTimes(occurrence);
      });
      expect(screen.getAllByText('391', { exact: true })).toHaveLength(occurrence);
      expect(vi.mocked(speakResponse)).toHaveBeenNthCalledWith(
        occurrence, '391', undefined, undefined, undefined, 'narration',
      );
    }
    expect(chatTexts().filter((message) => message.role === 'system').map((message) => message.text))
      .toEqual(['391', '391']);
    verify();
  });

  it.each([2, 3])('preserves the real result and node boundaries for scenario %s', async (index) => {
    const pair = calculatorPairs[index];
    const verify = installCalculatorFetch([pair]);
    useStore.setState({ voiceEnabled: true });
    render(<IntentSurface />);
    await ask(pair.request.message);
    await waitFor(() => expect(chatTexts().filter((message) => message.role === 'system'))
      .toEqual([{ role: 'system', text: pair.envelope.response }]));
    expect(vi.mocked(speakResponse)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(speakResponse).mock.calls[0][2]).toBeUndefined();
    expect(vi.mocked(speakResponse).mock.calls[0][4]).toBe('narration');
    expect(vi.mocked(speakResponse).mock.calls[0][0].replace(/\s+/g, ' ').trim())
      .toBe(pair.envelope.response.replace(/\s+/g, ' ').trim());
    verify();
  });

  it('keeps the real answer visible while voice is disabled', async () => {
    const pair = calculatorPairs[4];
    const verify = installCalculatorFetch([pair]);
    render(<IntentSurface />);
    await ask(pair.request.message);
    await waitFor(() => expect(chatTexts().filter((message) => message.role === 'system'))
      .toEqual([{ role: 'system', text: '391' }]));
    expect(screen.getByText('391', { exact: true })).toBeTruthy();
    expect(vi.mocked(speakResponse)).not.toHaveBeenCalled();
    verify();
  });

  it('rejects a mismatched request rather than serving a plausible cached answer', () => {
    const pair = calculatorPairs[0];
    expect(() => matchCalculatorPair({ ...pair.request, message: calculatorPairs[2].request.message }, pair))
      .toThrow();
    expect(() => matchCalculatorPair({ ...pair.request, attachment_ids: ['unrelated'] }, pair)).toThrow();
  });
});

describe('Issue 1378 fixture failure diagnostics', () => {
  it('resolves strict explicit overrides and local environments without scanning unrelated paths', async () => {
    const temporary = await mkdtemp(join(tmpdir(), 'probos-calculator-test-'));
    try {
      const executable = join(temporary, '.venv', 'Scripts', 'python.exe');
      await mkdir(dirname(executable), { recursive: true });
      await writeFile(executable, 'resolver-only fixture');
      expect(await resolveCalculatorPython(temporary, {})).toBe(await realpath(executable));
      expect(await resolveCalculatorPython(temporary, { PROBOS_TEST_PYTHON: '.venv/Scripts/python.exe' }))
        .toBe(await realpath(executable));
      expect(await resolveCalculatorPython(temporary, { PROBOS_PYTHON: executable }))
        .toBe(await realpath(executable));
      await expect(resolveCalculatorPython(temporary, {
        PROBOS_TEST_PYTHON: 'missing', PROBOS_PYTHON: executable,
      })).rejects.toThrow('PROBOS_TEST_PYTHON');
      await expect(resolveCalculatorPython(temporary, { PROBOS_PYTHON: 'missing' }))
        .rejects.toThrow('PROBOS_PYTHON');
      await rm(join(temporary, '.venv'), { recursive: true });
      await expect(resolveCalculatorPython(temporary, {})).rejects.toThrow('uv sync --group dev');
    } finally {
      await rm(temporary, { recursive: true, force: true });
    }
  });

  it('retains both the original child failure and a cleanup failure', async () => {
    const original = new Error('child traceback');
    const cleanupError = new Error('cleanup EBUSY');
    const remove = vi.fn<typeof rm>().mockRejectedValue(cleanupError);
    await expect(cleanupCalculatorDirectory('owned-fixture', original, remove))
      .rejects.toMatchObject({ errors: [original, cleanupError] });
    expect(remove).toHaveBeenCalledWith('owned-fixture', {
      recursive: true, force: true, maxRetries: 10, retryDelay: 100,
    });
    await expect(cleanupCalculatorDirectory('owned-fixture', undefined, remove)).rejects.toBe(cleanupError);
    remove.mockResolvedValue(undefined);
    await expect(cleanupCalculatorDirectory('owned-fixture', original, remove)).rejects.toBe(original);
  });

  it('retains executable and stderr evidence when JSON protocol parsing fails', () => {
    expect(() => parseCalculatorBatch('native-output\n{}', 'python-fixture exit=0 signal=none stderr-marker'))
      .toThrow('python-fixture exit=0 signal=none stderr-marker');
    expect(() => parseCalculatorBatch('{} trailing', 'bounded-context')).toThrow('bounded-context');
  });
});
