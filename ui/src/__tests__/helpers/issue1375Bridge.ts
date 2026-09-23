// Issue #1375: runs tests/fixtures/issue1375_work_state_bridge.py and returns the
// exact frame texts a real WSEventStreamHub sent and the exact REST bodies the
// production app served. Interpreter discovery is ownedStepsApi.test.ts's.
import { execFile } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { delimiter, dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveConsultedEvidencePython } from './consultedEvidenceBridge';

export type Issue1375Scenario = 'promoted_failed' | 'native_failed' | 'restart';

export interface Issue1375Rest {
  readonly status: number;
  readonly body: string;
}

export interface Issue1375Checkpoint {
  readonly name: string;
  readonly frames: readonly string[];
  readonly rest: Readonly<Record<string, Issue1375Rest>>;
}

export interface Issue1375Capture {
  readonly python: string;
  readonly origins: Readonly<Record<string, string>>;
  readonly elapsed_seconds: number;
  readonly ids: Readonly<Record<string, string>>;
  readonly checkpoints: readonly Issue1375Checkpoint[];
}

export interface Issue1375Run {
  readonly capture: Issue1375Capture;
  readonly wallMs: number;
}

export const ISSUE1375_BRIDGE_BUDGET_MS = 8_000;
// Kills a wedged child before Vitest's 10 s hook timeout would orphan it.
const BRIDGE_KILL_MS = 9_500;

const root = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../..'));

function assertCandidateOrigins(capture: Issue1375Capture, executable: string): void {
  if (realpathSync(capture.python) !== realpathSync(executable)) {
    throw new Error(`Issue 1375 bridge ran a foreign interpreter: ${capture.python}`);
  }
  const allowed = [join(root, 'src'), join(root, 'tests', 'fixtures'), join(root, 'ui', 'e2e', 'fixtures')];
  const origins = Object.entries(capture.origins);
  if (origins.length === 0) throw new Error('Issue 1375 bridge reported no module origins');
  for (const [name, origin] of origins) {
    const actual = realpathSync(origin);
    if (!allowed.some(parent => actual.startsWith(parent + sep))) {
      throw new Error(`Issue 1375 bridge module ${name} resolved outside the candidate tree: ${actual}`);
    }
  }
}

export async function runIssue1375Bridge(
  scenario: Issue1375Scenario,
  urlTemplates: readonly string[],
): Promise<Issue1375Run> {
  const executable = await resolveConsultedEvidencePython(root);
  const script = join(root, 'tests', 'fixtures', 'issue1375_work_state_bridge.py');
  const started = performance.now();
  const stdout = await new Promise<string>((accept, reject) => {
    execFile(executable, ['-u', script, root, scenario, JSON.stringify(urlTemplates)], {
      cwd: root, shell: false, windowsHide: true, encoding: 'utf8',
      maxBuffer: 16 * 1024 * 1024, timeout: BRIDGE_KILL_MS,
      env: {
        ...process.env, PYTHONPATH: [join(root, 'src'), root].join(delimiter),
        PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8',
        PROBOS_NATS_ENABLED: 'false', HF_HUB_OFFLINE: '1',
      },
    }, (error, output, stderr) => error
      ? reject(new Error(`Issue 1375 work-state bridge failed: ${error.message}\n${stderr}`))
      : accept(output));
  });
  const wallMs = performance.now() - started;
  const capture = JSON.parse(stdout) as Issue1375Capture;
  assertCandidateOrigins(capture, executable);
  return { capture, wallMs };
}
