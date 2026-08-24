import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchCrewTaskDetail, fetchRoomSummaries, repairRoomSummaries } from '../threadApi';
import type {
  CrewSessionDetailProjection,
  CrewSessionSummaryProjection,
  LegacyCrewChildView,
  LegacyCrewTaskTree,
  LegacyCrewVerdict,
  LegacyCrewWorkItemView,
} from '../../../store/types';

const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

function detail(): CrewSessionDetailProjection {
  return {
    task_id: 'parent-1',
    thread_id: 'thread-1',
    goal: 'Prepare report',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'facilitator-1',
    owner_ids: ['facilitator-1'],
    state: 'done',
    revision: 2,
    success_criteria: ['Complete'],
    expected_deliverable: 'Report',
    timestamps: {
      created_at: 1,
      transitioned_at: 3,
      started_at: 2,
      first_result_at: 2.5,
      verified_at: 3,
      completed_at: 3,
    },
    progress: { total: 1, done: 1, failed: 0, active: 0, active_child: null },
    last_result_summary: 'Complete',
    blocker: null,
    result: {
      artifact_id: 'artifact-1',
      content_hash: SHA_B,
      result_ref: SHA_A,
      evidence_refs: [SHA_A],
    },
    verification: {
      verifier_agent_id: 'verifier-1',
      confidence: 0.9,
      critique: 'Accepted',
      accepted_count: 1,
      total_count: 1,
      convergence_rounds: 1,
    },
    duplicate_resume_count: 0,
  };
}

function summary(): CrewSessionSummaryProjection {
  const source = detail();
  return {
    task_id: source.task_id,
    thread_id: source.thread_id,
    goal: source.goal,
    state: source.state,
    facilitator_id: source.facilitator_id,
    owner_ids: source.owner_ids,
    progress: { total: 1, done: 1, failed: 0, active: 0 },
    last_result_summary: source.last_result_summary,
    blocker: null,
    needs_attention: false,
    result_artifact_id: 'artifact-1',
    verified_at: 3,
  };
}

function legacyParent(): LegacyCrewWorkItemView {
  return {
    id: 'p1',
    title: 'Parent task',
    description: 'Coordinate the crew.',
    work_type: 'task',
    status: 'in_progress',
    priority: 3,
    parent_id: null,
    project_id: null,
    depends_on: [],
    assigned_to: 'facilitator-1',
    created_by: 'captain',
    created_at: 10,
    updated_at: 20,
    due_at: null,
    estimated_tokens: 500,
    actual_tokens: 120,
    trust_requirement: 0.5,
    required_capabilities: ['research'],
    tags: ['crew'],
    metadata: { source: 'captain' },
    steps: [{ label: 'Collect evidence', status: 'done' }],
    verification: { required: true },
    schedule: { cadence: 'once' },
    ttl_seconds: null,
    template_id: null,
  };
}

function legacyVerdict(): LegacyCrewVerdict {
  return {
    accepted: true,
    confidence: 0.9,
    critique: 'Accepted',
    verifier_agent_id: 'verifier-1',
    // BF-836: the validator checks an EXACT key set, so the fixture has to
    // carry this the moment the API does.
    verification_defect: false,
  };
}

function legacyChild(): LegacyCrewChildView {
  return {
    ...legacyParent(),
    id: 'c1',
    title: 'Child task',
    parent_id: 'p1',
    verdict: legacyVerdict(),
    rounds: 2,
  };
}

function legacyTree(): LegacyCrewTaskTree {
  return { parent: legacyParent(), children: [legacyChild()], count: 1 };
}

function withoutKey(value: object, key: string): Record<string, unknown> {
  const copy = { ...value } as Record<string, unknown>;
  delete copy[key];
  return copy;
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('AD-1132 threadApi CrewSession contracts', () => {
  it('returns a strict session detail success outcome', async () => {
    const owned = { ...detail(), task_id: 'parent/1' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ session: owned })));
    const outcome = await fetchCrewTaskDetail('parent/1');
    expect(fetch).toHaveBeenCalledWith('/api/crew-tasks/parent%2F1');
    expect(outcome).toEqual({ kind: 'success', response: { session: owned } });
  });

  it('distinguishes 404 empty from non-404 error and network error', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({}, 404))
      .mockResolvedValueOnce(response({}, 503))
      .mockRejectedValueOnce(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);
    expect(await fetchCrewTaskDetail('missing')).toEqual({ kind: 'empty' });
    expect(await fetchCrewTaskDetail('broken')).toEqual({ kind: 'error', status: 503 });
    expect(await fetchCrewTaskDetail('offline')).toEqual({ kind: 'error', status: null });
  });

  it('rejects malformed or additive detail keys instead of casting', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      session: { ...detail(), raw_metadata: { secret: 'x' } },
    })));
    expect(await fetchCrewTaskDetail('parent-1')).toEqual({ kind: 'error', status: 200 });
  });

  it('rejects a valid detail owned by a different parent without re-keying it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ session: detail() })));

    expect(await fetchCrewTaskDetail('outer-parent')).toEqual({
      kind: 'error',
      status: 200,
    });
  });

  it('accepts a complete exact real-shaped AD-862 legacy tree', async () => {
    const legacy = legacyTree();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(legacy)));
    expect(await fetchCrewTaskDetail('p1')).toEqual({ kind: 'success', response: legacy });
  });

  it('AD-1176: accepts a project-scoped legacy tree and rejects a missing project_id', async () => {
    // The legacy validator is exact-key, so WorkItem.project_id must be part
    // of the accepted shape — and its absence must still be rejected rather
    // than cast.
    const exact = legacyTree();
    const scoped: LegacyCrewTaskTree = {
      ...exact,
      parent: { ...exact.parent, project_id: 'proj-alpha' },
      children: [{ ...exact.children[0], project_id: 'proj-alpha' }],
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(scoped)));
    expect(await fetchCrewTaskDetail('p1')).toEqual({ kind: 'success', response: scoped });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...exact,
      parent: withoutKey(legacyParent(), 'project_id'),
    })));
    expect(await fetchCrewTaskDetail('p1')).toEqual({ kind: 'error', status: 200 });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...exact,
      parent: { ...exact.parent, project_id: 7 },
    })));
    expect(await fetchCrewTaskDetail('p1')).toEqual({ kind: 'error', status: 200 });
  });

  it('rejects partial, additive, or wrongly typed nested AD-862 values', async () => {
    const exact = legacyTree();
    const parent = legacyParent();
    const child = legacyChild();
    const verdict = legacyVerdict();
    const invalid: Array<[string, unknown]> = [
      ['missing parent key', { ...exact, parent: withoutKey(parent, 'title') }],
      ['additive parent key', { ...exact, parent: { ...parent, raw_metadata: {} } }],
      ['missing child key', { ...exact, children: [withoutKey(child, 'rounds')] }],
      ['additive child key', { ...exact, children: [{ ...child, raw_metadata: {} }] }],
      ['missing verdict key', {
        ...exact,
        children: [{ ...child, verdict: withoutKey(verdict, 'critique') }],
      }],
      ['additive verdict key', {
        ...exact,
        children: [{ ...child, verdict: { ...verdict, producer: 'raw' } }],
      }],
      ['wrong nested string-array type', {
        ...exact,
        parent: { ...parent, depends_on: [1] },
      }],
      ['wrong nested record type', {
        ...exact,
        children: [{ ...child, verification: [] }],
      }],
      ['wrong verdict field type', {
        ...exact,
        children: [{ ...child, verdict: { ...verdict, confidence: 'high' } }],
      }],
      ['wrong rounds type', { ...exact, children: [{ ...child, rounds: '2' }] }],
      // BF-836: the panel-level test for this only requires the generic error
      // state, which a validator that THREW would also produce. Asserted here,
      // where the result is `{kind:'error', status:200}` from a clean
      // rejection rather than from a catch. A key that is present but
      // malformed stays invalid -- only an ABSENT key is defaulted.
      ['non-boolean verification_defect', {
        ...exact,
        children: [{ ...child, verdict: { ...verdict, verification_defect: 'false' } }],
      }],
      // Pins `in` rather than `!== undefined` as the present/absent test.
      // JSON cannot carry `undefined`, but the decoder also runs on in-memory
      // objects; an own property explicitly set to `undefined` is PRESENT and
      // must therefore be refused, not quietly defaulted to null.
      ['own verification_defect explicitly undefined', {
        ...exact,
        children: [{ ...child, verdict: { ...verdict, verification_defect: undefined } }],
      }],
    ];

    for (const [label, value] of invalid) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(value)));
      expect(await fetchCrewTaskDetail('p1'), label).toEqual({
        kind: 'error',
        status: 200,
      });
    }
  });

  it('defaults an absent verification_defect to null rather than failing the tree', async () => {
    // BF-836 review: the verdict guard is reached through the child guard, so
    // before this default one missing key rejected the WHOLE tree and the
    // Captain lost the thread. Absence is exactly what the tri-state's `null`
    // means, so it decodes rather than refuses.
    const verdict = legacyVerdict();
    const stale = {
      ...legacyTree(),
      children: [{ ...legacyChild(), verdict: withoutKey(verdict, 'verification_defect') }],
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(stale)));

    const result = await fetchCrewTaskDetail('p1');

    expect(result.kind).toBe('success');
    const tree = (result as { response: LegacyCrewTaskTree }).response;
    expect(tree.children[0].verdict?.verification_defect).toBeNull();
    // Not coerced to false: `false` would assert the verifier was healthy.
    expect(tree.children[0].verdict?.verification_defect).not.toBe(false);
    // The rest of the verdict survives the rewrite untouched.
    expect(tree.children[0].verdict?.accepted).toBe(verdict.accepted);
    expect(tree.children[0].verdict?.critique).toBe(verdict.critique);
  });

  it('preserves exact generic summaries and accepts additive session summaries', async () => {
    const generic = { outputs: 1, steps_total: 2, steps_done: 1, topic: 'Generic' };
    const sessionRow = { ...generic, topic: 'Prepare report', session: summary() };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      summaries: { generic, 'thread-1': sessionRow },
    })));

    const result = await fetchRoomSummaries();

    expect(result.generic).toEqual(generic);
    expect(Object.keys(result.generic).sort()).toEqual([
      'outputs', 'steps_done', 'steps_total', 'topic',
    ]);
    expect(result['thread-1']).toEqual(sessionRow);
  });

  it('isolates malformed summary members while retaining valid siblings', async () => {
    const generic = { outputs: 0, steps_total: 0, steps_done: 0, topic: 'Generic' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      summaries: {
        generic,
        malformed: { ...generic, session: { task_id: 'partial' } },
      },
    })));
    expect(await fetchRoomSummaries()).toEqual({ generic });
  });

  it('degrades a wrong-thread session member to its validated generic summary', async () => {
    const generic = { outputs: 1, steps_total: 2, steps_done: 1, topic: 'Generic' };
    const validSession = summary();
    const mismatchedSession = { ...validSession, thread_id: 'embedded-thread' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      summaries: {
        generic,
        'thread-1': { ...generic, topic: validSession.goal, session: validSession },
        'outer-thread': { ...generic, topic: 'Legacy fallback', session: mismatchedSession },
      },
    })));

    const result = await fetchRoomSummaries();

    expect(result['thread-1']).toEqual({
      ...generic,
      topic: validSession.goal,
      session: validSession,
    });
    expect(result['outer-thread']).toEqual({
      ...generic,
      topic: 'Legacy fallback',
    });
    expect('session' in result['outer-thread']).toBe(false);
    expect(result).not.toHaveProperty('embedded-thread');
  });

  it('strict repair accepts authoritative empty and rejects a malformed sibling whole', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ summaries: {} })));
    expect(await repairRoomSummaries()).toEqual({ kind: 'success', summaries: {} });

    const generic = { outputs: 0, steps_total: 0, steps_done: 0, topic: 'Generic' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({
      summaries: { generic, malformed: { ...generic, raw: true } },
    })));
    expect(await repairRoomSummaries()).toEqual({ kind: 'error', status: 200 });
  });

  it('strict repair distinguishes transport failure from authoritative empty', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({}, 503)));
    expect(await repairRoomSummaries()).toEqual({ kind: 'error', status: 503 });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('offline')));
    expect(await repairRoomSummaries()).toEqual({ kind: 'error', status: null });
  });
});