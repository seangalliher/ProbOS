// Issue #1375: the committed capture the crossings replay. Frames are texts a real
// WSEventStreamHub sent and REST bodies texts the production app served, written by
// tests/fixtures/issue1375_work_state_bridge.py --write through a one-to-one ID and
// time map; tests/test_issue1375_work_state_reconciliation.py fails when it is stale.
import fixture from '../../../e2e/fixtures/issue1375_work_state.json';

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
  readonly ids: Readonly<Record<string, string>>;
  readonly checkpoints: readonly Issue1375Checkpoint[];
}

interface Issue1375Recorded extends Issue1375Capture {
  readonly url_templates: readonly string[];
}

const recorded: Readonly<Record<Issue1375Scenario, Issue1375Recorded>> = fixture.scenarios;

/** The scenario's capture; throws unless it was captured for exactly `urlTemplates`. */
export function loadIssue1375Capture(
  scenario: Issue1375Scenario,
  urlTemplates: readonly string[],
): Issue1375Capture {
  const { url_templates: captured, ids, checkpoints } = recorded[scenario];
  const stale = (why: string): Error => new Error(`Issue 1375 fixture ${why}; regenerate it: ${fixture.regenerate}`);
  if (JSON.stringify(captured) !== JSON.stringify(urlTemplates)) {
    throw stale(`captured ${scenario} for other URLs than this test requests`);
  }
  const urls = urlTemplates.map(template => Object.entries(ids)
    .reduce((url, [name, value]) => url.split(`{${name}}`).join(value), template)).sort();
  for (const checkpoint of checkpoints) {
    if (JSON.stringify(Object.keys(checkpoint.rest).sort()) !== JSON.stringify(urls)) {
      throw stale(`checkpoint ${scenario}/${checkpoint.name} holds other reads than this test requests`);
    }
  }
  return { ids, checkpoints };
}
