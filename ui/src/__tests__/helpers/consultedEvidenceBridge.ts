// AD-1243 (#1236) — Playwright-side bridge to the parent builder's real
// Python HTTP fixture (`tests/fixtures/consulted_evidence_bridge.py`, out of
// this slice's ownership) that drives real turns through the actual
// production `probos.api.create_app()` FastAPI app so the e2e crossing can
// consume genuine `GET /api/traces/{ref}/consulted` bytes.
//
// The fixture's verified protocol is mirrored here:
//   - Invocation: `python -u tests/fixtures/consulted_evidence_bridge.py <root> <owned-data>`,
//     stdio piped, cwd=<root>.
//   - Readiness (one line on the real stdout pipe once the fixture's actual
//     HTTP listener is bound): `{"kind":"ready","root","python","fixture",
//     "producer","agent","promotion","delivery","workforce","api","traces",
//     "origin"}`. The seven module-path fields are the fixture's own
//     candidate-origin proof (`fixture_origins()`); this bridge re-verifies
//     every one resolves under `<root>/src/probos` (and `fixture` under
//     `<root>/tests/fixtures`) before trusting `origin` at all.
//   - Commands (stdin, one JSON object per line, always answered):
//     `{op:"start", mode:"inline"|"promoted"|"outbox"|"lost_ack",
//       agent?:"yeo"|"other", thread?, query?, id}` starts one real turn
//       through the real agent/tool/promotion/delivery pipeline;
//     `{op:"release", turn, id}` releases a promoted/outbox/lost_ack turn's
//       scripted tool call so promotion/delivery actually happens (this is
//       the only way a real message gains `metadata.tool_trace_ref`);
//     `{op:"snapshot", turn, id}`, `{op:"recover", turn, id}`,
//     `{op:"threads", id}`, `{op:"state", id}`,
//     `{op:"auth", token, id}` (sets `runtime.config.auth.crew_scope_token`,
//       exercising the same auth path the real `/api/traces/*` routes use),
//     `{op:"stop", id}`.
//   - Responses: exactly one line per request, either
//     `{"kind":"response","id":<n>,"data":<result>}` or
//     `{"kind":"response","id":<n>,"error":"<ExceptionType>"}` — never an
//     `ok` boolean. The fixture's own dispatch loop terminates its command
//     loop after any error response, so a command error is treated here as
//     terminal for the bridge instance, never silently retried.
// Wire bytes this bridge reads (raw `fetch(...).arrayBuffer()`, never
// `.json()`) are forwarded verbatim by the spec's route handler — nothing
// here parses-and-reserializes a real HTTP response body.
import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { createInterface } from 'node:readline';
import { delimiter, dirname, join, resolve } from 'node:path';

const nativeWireFetch = globalThis.fetch;

/** Mirrors `resolveCalculatorPython` in `IntentSurface.bf812.test.tsx` verbatim
 * (env-var override, else local `.venv`, else shared-worktree `.venv` via
 * `git rev-parse --git-common-dir`) so both fixtures fail the same way for
 * the same reason — a missing interpreter is a hard failure, never a skip. */
export async function resolveConsultedEvidencePython(
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
    return candidate;
  }
  const candidates = ['.venv/Scripts/python.exe', '.venv/bin/python'].map((relative) => join(root, relative));
  const local = candidates.find(isFile);
  if (local) return local;
  let commonDirectory: string;
  try {
    const output = await new Promise<string>((accept, reject) => {
      execFile('git', ['-C', root, 'rev-parse', '--git-common-dir'], {
        shell: false, timeout: 5_000, maxBuffer: 65_536, encoding: 'utf8',
      }, (error, stdout) => (error ? reject(error) : accept(stdout.trim())));
    });
    if (!output) throw new Error('Git returned an empty common directory');
    const { realpath } = await import('node:fs/promises');
    commonDirectory = await realpath(resolve(root, output));
  } catch (error) {
    throw Object.assign(new Error(
      'Cannot resolve the backend test environment for the consulted-evidence fixture. '
      + 'Set PROBOS_TEST_PYTHON or PROBOS_PYTHON, or run '
      + 'uv sync --group dev --extra discovery --extra browser in the repository.',
    ), { cause: error });
  }
  candidates.push(...['.venv/Scripts/python.exe', '.venv/bin/python']
    .map((relative) => join(dirname(commonDirectory), relative)));
  const common = candidates.find(isFile);
  if (common) return common;
  throw new Error(
    'No backend test interpreter found for the consulted-evidence fixture. '
    + 'Set PROBOS_TEST_PYTHON or PROBOS_PYTHON, or run '
    + 'uv sync --group dev --extra discovery --extra browser. Checked: '
    + candidates.join(', '),
  );
}

/** Mirrors `cleanupCalculatorDirectory` in `IntentSurface.bf812.test.tsx`:
 * a bounded-retry removal that never swallows the original failure. */
export async function cleanupConsultedEvidenceDirectory(
  temporary: string, originalError: unknown, remove: typeof rm = rm,
): Promise<void> {
  try {
    await remove(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  } catch (cleanupError) {
    if (originalError !== undefined) {
      throw Object.assign(new Error('Consulted-evidence fixture use and cleanup both failed'), {
        errors: [originalError, cleanupError], cause: originalError,
      });
    }
    throw cleanupError;
  }
  if (originalError !== undefined) throw originalError;
}

/** Verbatim sentinels/constants mirrored from `consulted_evidence_bridge.py`
 * (not imported — that file is not owned by this slice). The e2e spec must
 * assert the two "DoNotRender" sentinels never appear anywhere in the DOM. */
export const SENSITIVE_SENTINEL = 'AD1243_SYNTHETIC_SECRET_DoNotRender';
export const OUTPUT_SENTINEL = 'AD1243_PRIVATE_OUTPUT_DoNotRender';
export const FIXTURE_REPOSITORY = 'langchain-ai/langchain';
export const FIXTURE_REPLY_BODY = 'Consulted the requested repository notes.';

interface Ready {
  kind: 'ready'; root: string; python: string; fixture: string;
  producer: string; agent: string; promotion: string; delivery: string;
  workforce: string; api: string; traces: string; origin: string;
}
interface CommandResponse { kind: 'response'; id: number; data?: unknown; error?: string }

/** Raw wire shape of `ChatThreadMessage.to_dict()` (`src/probos/threads/__init__.py`) —
 * snake_case, unconverted; the real frontend (not this bridge) maps this to
 * `AgentProfileMessage`'s camelCase shape once served through the real API. */
export interface FixtureThreadMessage {
  id: string; thread_id: string; author_id: string; role: string; body: string;
  created_at: number; metadata: Record<string, unknown>;
}
export interface FixtureThread {
  id: string; title: string; participants: string[]; project_id: string | null;
  task_id: string | null; pinned: boolean; archived: boolean;
  personality_override: string | null; workspace_root: string | null;
  created_at: number; last_active_at: number; preprompt: string | null;
  model: string | null; metadata: Record<string, unknown>;
}
export interface TurnSnapshot {
  turn: string; mode: string; agent: string; thread: FixtureThread;
  messages: FixtureThreadMessage[]; pending: unknown[]; reply: unknown;
  llm_calls: number; tool_calls: number; query: string; body: string;
  repo: string; released: boolean; attempts: unknown[];
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
  let resolveFn!: (value: T) => void;
  let rejectFn!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolveFn = res; rejectFn = rej; });
  return { promise, resolve: resolveFn, reject: rejectFn };
}

function normalize(path: string): string {
  return resolve(path).replace(/\\/g, '/');
}

function isUnder(candidate: string, parent: string): boolean {
  const normalizedCandidate = normalize(candidate);
  const normalizedParent = normalize(parent).replace(/\/$/, '');
  return normalizedCandidate === normalizedParent || normalizedCandidate.startsWith(`${normalizedParent}/`);
}

/**
 * Spawns and owns the parent builder's real consulted-evidence HTTP fixture
 * for exactly one Playwright spec run. Missing prerequisites are hard
 * failures (thrown from `boot()`), never a silent skip — a fixture that
 * doesn't exist yet must be visible as a failing test, not green noise.
 */
export class ConsultedEvidenceBridge {
  readonly root: string;
  readonly fixturePath: string;
  child: ChildProcessWithoutNullStreams | null = null;
  origin = '';
  private readonly ready = deferred<Ready>();
  private sequence = 0;
  private readonly pending = new Map<number, ReturnType<typeof deferred<CommandResponse>>>();
  private stderrTail = '';
  private terminal = false;
  private ownedData: string | null = null;
  private lifetime: ReturnType<typeof setTimeout> | undefined;
  private readonly wireFetch = nativeWireFetch;

  constructor(root: string) {
    this.root = root;
    this.fixturePath = join(root, 'tests', 'fixtures', 'consulted_evidence_bridge.py');
  }

  /** Resolves once the fixture's real HTTP listener is bound and ready, after
   * verifying every reported module path is a genuine candidate under
   * `<root>/src/probos` (mirroring the fixture's own `fixture_origins()`). */
  async boot(pythonOverride?: string): Promise<string> {
    if (this.child) throw new Error('Consulted-evidence fixture is already started');
    if (!existsSync(this.fixturePath)) {
      throw new Error(
        `Missing prerequisite: the parent-owned fixture does not exist yet at ${this.fixturePath}. `
        + 'This slice does not own that file; the e2e crossing cannot run until it is added — '
        + 'failing loudly rather than skipping.',
      );
    }
    const python = pythonOverride ?? await resolveConsultedEvidencePython(this.root);
    this.ownedData = await mkdtemp(join(tmpdir(), 'probos-consulted-owned-'));
    const child = spawn(python, ['-u', this.fixturePath, this.root, this.ownedData], {
      cwd: this.root, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      env: {
        SystemRoot: process.env.SystemRoot ?? 'C:\\Windows',
        PATH: `${dirname(python)};${process.env.SystemRoot ?? 'C:\\Windows'}\\System32`,
        PYTHONPATH: `${resolve(this.root, 'src')}${delimiter}${this.root}`,
        PYTHONNOUSERSITE: '1', PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1',
        PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1',
      },
    });
    this.child = child;
    const fail = (error: Error): void => {
      this.terminal = true;
      this.ready.reject(error);
      for (const request of this.pending.values()) request.reject(error);
      this.pending.clear();
    };
    this.lifetime = setTimeout(() => {
      fail(new Error('Owned consulted fixture exceeded its 150-second lifetime'));
      child.kill();
    }, 150_000);
    child.stderr.on('data', (chunk) => { this.stderrTail = (this.stderrTail + String(chunk)).slice(-12_000); });
    const lines = createInterface({ input: child.stdout });
    lines.on('line', (line) => {
      let message: Ready | CommandResponse;
      try {
        message = JSON.parse(line) as Ready | CommandResponse;
      } catch {
        fail(new Error('Owned consulted fixture emitted invalid protocol data'));
        return;
      }
      if (message.kind === 'ready') this.ready.resolve(message);
      else if (message.kind === 'response') {
        const request = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (!request) return;
        if (message.error === undefined) request.resolve(message);
        else {
          this.terminal = true; // The fixture's own loop breaks after any error response.
          request.reject(new Error(`${message.error}: ${this.stderrTail}`));
        }
      }
    });
    child.on('error', fail);
    child.stdin.on('error', fail);
    child.on('exit', (code) => {
      clearTimeout(this.lifetime);
      lines.close();
      fail(new Error(`Consulted-evidence fixture exited ${code}: ${this.stderrTail}`));
    });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_r, reject) => {
      timer = setTimeout(
        () => reject(new Error(`Consulted-evidence fixture never became ready: ${this.stderrTail}`)), 20_000,
      );
    });
    try {
      const ready = await Promise.race([this.ready.promise, timeout]);
      this.verifyCandidateOrigin(ready, python);
      this.origin = ready.origin;
      return this.origin;
    } catch (error) {
      await this.stop();
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Strict candidate-origin check, mirroring `fixture_origins()`: every
   * reported module path must resolve under `<root>/src/probos`, the
   * fixture path itself under `<root>/tests/fixtures`, and the reported
   * root/python must match what this bridge asked for. */
  private verifyCandidateOrigin(ready: Ready, python: string): void {
    if (normalize(ready.root) !== normalize(this.root)) {
      throw new Error(`Consulted-evidence fixture reported a foreign root: ${ready.root}`);
    }
    if (normalize(ready.python) !== normalize(python)) {
      throw new Error(`Consulted-evidence fixture reported a foreign interpreter: ${ready.python}`);
    }
    if (normalize(ready.fixture) !== normalize(this.fixturePath)) {
      throw new Error(`Consulted-evidence fixture reported a foreign fixture path: ${ready.fixture}`);
    }
    const srcProbos = join(this.root, 'src', 'probos');
    const expected = {
      producer: 'cognitive/agentic_dispatch.py', agent: 'cognitive/cognitive_agent.py',
      promotion: 'cognitive/turn_promotion.py', delivery: 'cognitive/promoted_report_delivery.py',
      workforce: 'workforce.py', api: 'api.py', traces: 'routers/traces.py',
    };
    for (const key of ['producer', 'agent', 'promotion', 'delivery', 'workforce', 'api', 'traces'] as const) {
      if (!isUnder(ready[key], srcProbos) || normalize(ready[key]) !== normalize(join(srcProbos, expected[key]))) {
        throw new Error(`Consulted-evidence fixture reported a foreign candidate module for ${key}: ${ready[key]}`);
      }
    }
    if (!/^https?:\/\/127\.0\.0\.1:\d+$/.test(ready.origin)) {
      throw new Error(`Consulted-evidence fixture reported a non-loopback origin: ${ready.origin}`);
    }
  }

  private async command(payload: Record<string, unknown>): Promise<unknown> {
    if (!this.child) throw new Error('Consulted-evidence fixture is not started');
    if (this.terminal) throw new Error('Consulted-evidence fixture already terminated after a prior command error');
    const id = ++this.sequence;
    const result = deferred<CommandResponse>();
    this.pending.set(id, result);
    const timer = setTimeout(() => {
      this.pending.delete(id);
      result.reject(new Error(`Consulted-evidence fixture command timed out: ${payload.op}; ${this.stderrTail}`));
    }, 15_000);
    try {
      this.child.stdin.write(`${JSON.stringify({ ...payload, id })}\n`);
      const response = await result.promise;
      return response.data;
    } finally {
      clearTimeout(timer);
    }
  }

  async startTurn(
    mode: 'inline' | 'promoted' | 'outbox' | 'lost_ack',
    options: { agent?: 'yeo' | 'other'; thread?: string; query?: string } = {},
  ): Promise<TurnSnapshot> {
    return await this.command({ op: 'start', mode, ...options }) as TurnSnapshot;
  }

  async releaseTurn(turn: string): Promise<TurnSnapshot> {
    return await this.command({ op: 'release', turn }) as TurnSnapshot;
  }

  async snapshotTurn(turn: string): Promise<TurnSnapshot> {
    return await this.command({ op: 'snapshot', turn }) as TurnSnapshot;
  }

  async recoverTurn(turn: string): Promise<TurnSnapshot & { recovered: unknown }> {
    return await this.command({ op: 'recover', turn }) as TurnSnapshot & { recovered: unknown };
  }

  async listThreads(): Promise<FixtureThread[]> {
    return await this.command({ op: 'threads' }) as FixtureThread[];
  }

  async state(): Promise<unknown> {
    return await this.command({ op: 'state' });
  }

  async fetchWire(path: string, init: RequestInit = {}): Promise<Response> {
    if (!this.origin || !path.startsWith('/api/') || path.includes('\\')) {
      throw new Error('Owned consulted HTTP path invalid');
    }
    const target = new URL(path, this.origin);
    if (target.origin !== this.origin) throw new Error('Owned consulted HTTP origin invalid');
    return this.wireFetch(target, { ...init, redirect: 'error' });
  }

  /** Sets `runtime.config.auth.crew_scope_token` on the real runtime — an
   * empty string restores the pass-through (no-auth-required) behavior. */
  async setAuth(token: string): Promise<{ configured: boolean }> {
    return await this.command({ op: 'auth', token }) as { configured: boolean };
  }

  async setReceiptStoreAvailable(available: boolean): Promise<void> {
    await this.command({ op: 'receipt_store', available });
  }

  async stop(): Promise<void> {
    const child = this.child;
    try {
      if (child?.pid && child.exitCode === null && child.signalCode === null) {
        if (!this.terminal) {
          await this.command({ op: 'stop' }).catch(() => { /* bounded kill remains the fallback */ });
        }
        child.stdin.end();
        await new Promise<void>((resolveExit, reject) => {
          if (child.exitCode !== null || child.signalCode !== null) { resolveExit(); return; }
          const kill = setTimeout(() => { child.kill(); }, 5000);
          const deadline = setTimeout(() => reject(new Error('Owned consulted child did not exit')), 10_000);
          child.once('exit', () => { clearTimeout(kill); clearTimeout(deadline); resolveExit(); });
        });
      }
    } finally {
      clearTimeout(this.lifetime);
      if (child?.pid && child.exitCode === null && child.signalCode === null) child.kill();
      const ownedData = this.ownedData;
      this.ownedData = null;
      if (ownedData) await cleanupConsultedEvidenceDirectory(ownedData, undefined);
    }
  }
}
