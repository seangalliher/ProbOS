import { execFile } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { delimiter, dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { resolveConsultedEvidencePython } from '../../../__tests__/helpers/consultedEvidenceBridge';
import {
  OwnedStepsApiError,
  applyOwnedProposal,
  fetchOwnedRepair,
  fetchOwnedStepDetail,
  fetchOwnedSteps,
  finalizeOwnedSteps,
  previewOwnedProposal,
  sendOwnedCommands,
} from '../ownedStepsApi';

const digest = (character: string) => character.repeat(64);

const reference = {
  version: 1 as const,
  parent_id: 'parent-1',
  actor_id: 'captain',
  thread_id: '',
  turn_id: 'http-owner',
  view_id: 'view-1',
  content_hash: digest('a'),
};

function managedView() {
  return {
    version: 1,
    parent_id: 'parent-1',
    requested_item_id: 'child-1',
    actor_id: 'captain',
    thread_id: '',
    turn_id: 'http-owner',
    view_id: 'view-1',
    mode: 'active',
    layout_revision: 1,
    plan_revision: 1,
    plan_digest: digest('b'),
    steps_digest: digest('c'),
    source_digest: digest('d'),
    plan_token: {},
    rows: [{
      step_id: 'step-1',
      ordinal: 1,
      kind: 'manual',
      child_id: null,
      revision: 1,
      digest: digest('e'),
      todo: {
        label: 'Review',
        status: 'submitted',
        assigned_to: null,
        submitted_by: 'worker',
        confirmed_by: null,
        note: null,
      },
      actions: ['manual_confirm', 'manual_reject'],
      evidence: {
        permit_state: 'unstarted',
        assignment_epoch: 1,
        booking_id: null,
        has_submission: false,
        review_accepted: null,
      },
      token: {
        parent_id: 'parent-1',
        incarnation: 'inc-1',
        layout_revision: 1,
        plan_revision: 1,
        plan_digest: digest('b'),
        step_id: 'step-1',
        row_revision: 1,
        row_digest: digest('e'),
        source_digest: null,
        assignment_epoch: 1,
        actor_id: 'captain',
        thread_id: '',
        view_id: 'view-1',
        turn_id: 'http-owner',
      },
      detail_url: null,
    }],
    previous_cursor: null,
    next_cursor: '20',
    omitted_step_ids: [],
    recovery: [],
    finalization: 'none',
    reference,
  };
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

interface LongRowWire {
  parent_id: string;
  step_id: string;
  label: string;
  page: string;
  detail: string;
  legacy: string;
  raw_steps: string;
  model_view: string;
  model_reference: string;
  unpresented_code: string;
  readonly_code: string;
  hidden_http_code: string | null;
}

async function longRowBackendWires(): Promise<LongRowWire[]> {
  const root = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..'));
  const executable = await resolveConsultedEvidencePython(root);
  // Reuse the owned-step backend test wiring with an in-memory database/content
  // store. HTTP bodies cross as response.text, never as JS-reserialized fixtures.
  const stdout = await new Promise<string>((accept, reject) => {
    execFile(executable, ['-u', '-c', `
import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from probos import api, work_item_steps as steps, workforce
from probos.cognitive import cognitive_agent, crew_orchestrator, crew_session
from probos.config import SystemConfig
from tests import test_ad1192_owned_steps_dm as bridge

root = Path(sys.argv[1]).resolve()
modules = (api, steps, workforce, cognitive_agent, crew_orchestrator, crew_session)
origins = {module.__name__: str(Path(module.__file__).resolve()) for module in modules}
assert all(Path(origin).is_relative_to(root / "src") for origin in origins.values())
assert Path(bridge.__file__).resolve() == root / "tests" / "test_ad1192_owned_steps_dm.py"

class MemoryAttachments:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(self, content_hash: str, blob: bytes, mime: str, *, origin: str) -> None:
        assert steps.owned_digest(blob) == content_hash
        assert mime == "application/json" and origin == "agent_artifact"
        self.blobs[content_hash] = blob

    async def read(self, content_hash: str) -> bytes:
        return self.blobs[content_hash]

    async def size(self, content_hash: str) -> int:
        return len(self.blobs[content_hash])

async def collect() -> list[dict[str, object]]:
    store = workforce.WorkItemStore(":memory:", tick_interval=1000)
    await store.start()
    attachments = MemoryAttachments()
    service = crew_session.CrewSessionService(
        work_item_store=store, chat_thread_store=object(),
        registry=bridge._Registry(), trust_network=bridge._Trust(),
    )
    config = SystemConfig()
    config.dm_agentic.enabled = False
    config.attachments.enabled = False
    config.communications.room_awareness_enabled = False
    runtime = SimpleNamespace(
        work_item_store=store, attachment_store=attachments,
        crew_session_service=service, config=config,
    )
    owner = crew_orchestrator.CrewOrchestrator(
        assignment_resolver=object(), delegator=object(),
        crew_executor=bridge._Executor(store), verifier=bridge._Verifier(),
        synthesizer=bridge._Synthesizer(), work_item_store=store,
        runtime=runtime, crew_session_service=service,
    )
    runtime.crew_orchestrator = owner
    result = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api.create_app(runtime)), base_url="http://test",
        ) as client:
            for length in (5000, 20000):
                parent_id = "long-row-probe" if length == 5000 else "oversized-row-probe"
                label = "x" * length
                parent = await store.create_work_item(
                    id=parent_id, title="Long row", steps=[{"label": label, "status": "pending"}],
                )
                child = await store.create_work_item(
                    id=parent_id + "-child", title="Child", parent_id=parent.id,
                    assigned_to="reader-agent", metadata={"spec_id": parent_id + "-spec"},
                )
                await store.get_owned_steps_execution_port().admit(
                    parent.id, children=(child,), thread_id="",
                )
                before = await store.read_owned_steps_raw_identity(parent.id)
                snapshot = await store.get_owned_steps(parent.id)
                assert before is not None and snapshot is not None
                step_id = snapshot.control.rows[0].step_id
                page = await client.get(f"/api/work-items/{parent.id}/owned-steps")
                detail = await client.get(
                    f"/api/work-items/{parent.id}/owned-steps", params={"detail": step_id},
                )
                legacy = await client.get(f"/api/work-items/{parent.id}/steps")
                assert page.status_code == detail.status_code == legacy.status_code == 200
                assert detail.json()["todo"]["label"] == label
                assert detail.json()["read_only"] is True
                assert set(legacy.json()) == {"steps", "gate_completion"}
                assert legacy.json()["steps"] == json.loads(before.raw_steps)
                if length == 5000:
                    assert len(page.content) == 7415
                    assert page.json()["rows"][0]["todo"]["label"] == label
                else:
                    assert page.json()["rows"] == []
                    assert page.json()["omitted_step_ids"] == [step_id]
                    assert {"detail", "view_budget"} <= set(page.json()["recovery"])

                hidden_http_code = None
                if length == 20000:
                    rejected = await client.post(
                        f"/api/work-items/{parent.id}/owned-steps/commands",
                        json={"version": 1, "reference": page.json()["reference"], "commands": [{
                            "operation_id": "hidden-http", "step_id": step_id, "kind": "manual_submit",
                        }]},
                    )
                    assert rejected.status_code == 409
                    hidden_http_code = rejected.json()["detail"]["code"]
                    assert hidden_http_code == "owned_steps_hidden_or_unpresented"

                context = await owner.owned_steps_actual_context(
                    service.agent_principal("reader-agent"),
                    work_item_id=parent.id, turn_id=f"model-{length}",
                )
                reference = await owner.capture_owned_steps_view(context, requested_item_id=parent.id)
                raw = await attachments.read(reference.content_hash)
                batch = steps.OwnedStepsCommandBatch(reference=reference, commands=(
                    steps.OwnedStepsHttpRowCommand(
                        operation_id=f"model-write-{length}", step_id=step_id, kind="manual_submit",
                    ),
                ))
                async def refused_code() -> str:
                    try:
                        await owner.apply_owned_steps_commands(batch, context)
                    except steps.OwnedStepsError as exc:
                        return exc.code
                    raise AssertionError("Readonly model view unexpectedly authorized a write")

                unpresented_code = await refused_code()
                assert unpresented_code == "owned_steps_view_unpresented"
                llm = bridge._CaptureLLM()
                agent = bridge._OwnedViewAgent(
                    agent_id="reader-agent", llm_client=llm, runtime=runtime,
                )
                params = {
                    "text": "captain raw", "captain_message": "captain raw",
                    "owned_steps_view": reference.model_dump(mode="json"),
                }
                original_params = copy.deepcopy(params)
                intent = bridge.IntentMessage(
                    intent="direct_message", params=params, target_agent_id=agent.id, thread_id="",
                )
                decision = await agent.decide(await agent.perceive(intent))
                assert decision["llm_output"] == "observed" and len(llm.requests) == 1
                presented = bridge._request_text(llm.requests[0]).split(
                    "<owned_steps_view>\\n", 1,
                )[1].split("\\n</owned_steps_view>", 1)[0]
                assert presented.encode("utf-8") == raw
                assert params == original_params
                assert len(raw) <= 16 * 1024
                assert len(steps.owned_json_bytes(params)) <= 4096
                readonly_code = await refused_code()
                assert readonly_code == "owned_steps_hidden_or_unpresented"
                after = await store.read_owned_steps_raw_identity(parent.id)
                assert after.raw_steps == before.raw_steps and after.raw_control == before.raw_control
                assert (await client.get(f"/api/work-items/{parent.id}/steps")).text == legacy.text
                result.append({
                    "parent_id": parent.id, "step_id": step_id, "label": label,
                    "page": page.text, "detail": detail.text, "legacy": legacy.text,
                    "raw_steps": before.raw_steps, "model_view": presented,
                    "model_reference": json.dumps(params["owned_steps_view"]),
                    "unpresented_code": unpresented_code, "readonly_code": readonly_code,
                    "hidden_http_code": hidden_http_code,
                })
                await owner.expire_owned_steps_views(context)
        return result
    finally:
        await owner.stop()
        await store.stop()

sys.stdout.write(json.dumps({
    "python": sys.executable, "fixture": bridge.__file__, "origins": origins,
    "wires": asyncio.run(collect()),
}, ensure_ascii=False, allow_nan=False))
`, root], {
      cwd: root, shell: false, windowsHide: true, encoding: 'utf8',
      env: {
        ...process.env, PYTHONPATH: [join(root, 'src'), root].join(delimiter),
        PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8',
        PROBOS_NATS_ENABLED: 'false', HF_HUB_OFFLINE: '1',
      },
    }, (error, output, stderr) => error
      ? reject(new Error(`Owned-step wire bridge failed: ${error.message}\n${stderr}`))
      : accept(output));
  });
  const result = JSON.parse(stdout) as {
    python: string; fixture: string; origins: Record<string, string>; wires: LongRowWire[];
  };
  expect(realpathSync(result.python)).toBe(realpathSync(executable));
  expect(realpathSync(result.fixture)).toBe(join(root, 'tests/test_ad1192_owned_steps_dm.py'));
  expect(Object.keys(result.origins)).toHaveLength(6);
  for (const origin of Object.values(result.origins)) {
    expect(realpathSync(origin).startsWith(join(root, 'src') + sep)).toBe(true);
  }
  return result.wires;
}

function wireResponse(wire: string): Response {
  return { ok: true, status: 200, text: async () => wire } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('owned steps API', () => {
  it('decodes a strict managed child-resolved page with immutable metadata outside the Todo', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(managedView())));

    const view = await fetchOwnedSteps('child-1', { cursor: '20' });

    expect(view.mode).toBe('active');
    if (view.mode === 'unmanaged') throw new Error('expected managed');
    expect(view.requested_item_id).toBe('child-1');
    expect(view.rows[0].todo).toEqual(managedView().rows[0].todo);
    expect(view.rows[0].step_id).toBe('step-1');
    expect(fetch).toHaveBeenCalledWith('/api/work-items/child-1/owned-steps?cursor=20', undefined);
  });

  it('decodes a readonly managed page without plan or row write tokens', async () => {
    const managed = managedView();
    const body = {
      ...managed,
      plan_token: null,
      rows: [{
        ...managed.rows[0],
        token: null,
        actions: [],
      }],
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));

    const view = await fetchOwnedSteps('child-1');

    if (view.mode === 'unmanaged') throw new Error('expected managed');
    expect(view.plan_token).toBeNull();
    expect(view.rows[0].token).toBeNull();
    expect(view.rows[0].actions).toEqual([]);
  });

  it('keeps a known unmanaged response distinct from an ownership read failure', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        version: 1,
        mode: 'unmanaged',
        parent_id: 'plain-1',
        requested_item_id: 'plain-1',
        reference: null,
        rows: [{ ordinal: 1, todo: { label: 'Manual', status: 'pending' } }],
        previous_cursor: null,
        next_cursor: null,
        recovery: [],
        finalization: 'none',
      }))
      .mockResolvedValueOnce(response({
        detail: {
          code: 'owned_steps_unavailable',
          message: 'Owner unavailable.',
          parent_id: 'plain-1',
          view_id: null,
          actions: ['refresh'],
          feedback: 'Owned steps unavailable. Refresh.',
        },
      }, 503));
    vi.stubGlobal('fetch', fetchMock);

    expect((await fetchOwnedSteps('plain-1')).mode).toBe('unmanaged');
    await expect(fetchOwnedSteps('plain-1')).rejects.toMatchObject({
      name: 'OwnedStepsApiError',
      status: 503,
      code: 'owned_steps_unavailable',
      feedback: 'Owned steps unavailable. Refresh.',
    });
  });

  it('rejects unknown row metadata rather than treating it as unmanaged', async () => {
    const body = managedView();
    (body.rows[0] as Record<string, unknown>).authority = 'captain';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(fetchOwnedSteps('parent-1')).rejects.toMatchObject({
      code: 'owned_steps_malformed_row',
    });
  });

  describe('real long-row owned HTTP wire', () => {
    let wires: LongRowWire[];

    beforeAll(async () => { wires = await longRowBackendWires(); });

    it('decodes the actual 7415-byte page with an unchanged 5000-character label', async () => {
      const wire = wires[0];
      expect(wire.label).toHaveLength(5000);
      expect(new TextEncoder().encode(wire.page).byteLength).toBe(7415);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(wireResponse(wire.page)));

      const view = await fetchOwnedSteps(wire.parent_id);

      expect(view).toEqual(JSON.parse(wire.page));
      expect(view.rows[0].todo.label).toBe(wire.label);
      expect(JSON.parse(wire.raw_steps)[0].label).toBe(wire.label);
      expect(JSON.parse(wire.legacy)).toEqual({
        steps: [{ label: wire.label, status: 'pending' }],
        gate_completion: false,
      });
    });

    // The previous "Large evidence" fixture was short: it never exercised the
    // 4096-character mismatch or the backend's oversized-row detail recovery.
    it.each([0, 1])('decodes readonly oversized-row detail without issuing a write token (%s)', async (index) => {
      const wire = wires[index];
      expect(wire.label.length).toBeGreaterThan(4096);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(wireResponse(wire.detail)));

      const detail = await fetchOwnedStepDetail(wire.parent_id, wire.step_id);

      expect(detail).toEqual(JSON.parse(wire.detail));
      expect(detail.todo).toMatchObject({ label: wire.label });
      expect(detail.read_only).toBe(true);
      expect(detail).not.toHaveProperty('token');
      expect(detail).not.toHaveProperty('actions');
    });

    it('keeps the oversized page omitted and recovers the full row only as readonly detail', async () => {
      const wire = wires[1];
      vi.stubGlobal('fetch', vi.fn()
        .mockResolvedValueOnce(wireResponse(wire.page))
        .mockResolvedValueOnce(wireResponse(wire.detail)));

      const view = await fetchOwnedSteps(wire.parent_id);
      if (view.mode === 'unmanaged') throw new Error('expected managed');
      expect(view.rows).toEqual([]);
      expect(view.omitted_step_ids).toEqual([wire.step_id]);
      expect(view.recovery).toEqual(expect.arrayContaining(['detail', 'view_budget']));
      const detail = await fetchOwnedStepDetail(wire.parent_id, view.omitted_step_ids[0]);

      expect(detail.todo).toMatchObject({ label: wire.label });
      expect(wire.label).toHaveLength(20000);
      expect(detail.read_only).toBe(true);
      expect(detail).not.toHaveProperty('token');
      expect(wire.hidden_http_code).toBe('owned_steps_hidden_or_unpresented');
    });

    it.each([0, 1])('preserves actual model presentation, reference bounds, and readonly authority (%s)', (index) => {
      const wire = wires[index];
      const presented = JSON.parse(wire.model_view);
      const descriptor = JSON.parse(wire.model_reference);
      expect(new TextEncoder().encode(wire.model_view).byteLength).toBeLessThanOrEqual(16 * 1024);
      expect(new TextEncoder().encode(wire.model_reference).byteLength).toBeLessThanOrEqual(4096);
      expect(descriptor).not.toHaveProperty('rows');
      expect(presented.plan_token).toBeNull();
      if (index === 0) {
        expect(presented.rows[0].todo.label).toBe(wire.label);
        expect(presented.rows[0].token).toBeNull();
        expect(presented.rows[0].actions).toEqual([]);
      } else {
        expect(presented.rows).toEqual([]);
        expect(presented.omitted_step_ids).toEqual([wire.step_id]);
        expect(wire.model_view).not.toContain(wire.label);
      }
      expect(wire.unpresented_code).toBe('owned_steps_view_unpresented');
      expect(wire.readonly_code).toBe('owned_steps_hidden_or_unpresented');
    });

    it.each(['page', 'detail'] as const)('retains the 1 MiB UTF-8 wire bound for %s', async (kind) => {
      const wire = wires[0];
      const body = JSON.parse(wire[kind]);
      const todo = kind === 'page' ? body.rows[0].todo : body.todo;
      todo.label = '\u00e9'.repeat(512 * 1024);
      const oversized = JSON.stringify(body);
      expect(oversized.length).toBeLessThan(1024 * 1024);
      expect(new TextEncoder().encode(oversized).byteLength).toBeGreaterThan(1024 * 1024);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(wireResponse(oversized)));

      await expect(kind === 'page'
        ? fetchOwnedSteps(wire.parent_id)
        : fetchOwnedStepDetail(wire.parent_id, wire.step_id)).rejects.toMatchObject({
        code: 'owned_steps_response_too_large',
      });
    });

    it.each([
      ['empty label', { label: '' }],
      ['non-string label', { label: null }],
      ['historical status', { status: 'completed' }],
      ['unknown Todo key', { authority: 'captain' }],
      ['non-string note', { note: 1 }],
    ])('still rejects %s in a long-row Todo', async (_name, change) => {
      const wire = wires[0];
      const body = JSON.parse(wire.detail);
      Object.assign(body.todo, change);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));

      await expect(fetchOwnedStepDetail(wire.parent_id, wire.step_id)).rejects.toMatchObject({
        code: 'owned_steps_malformed_todo',
      });
    });
  });

  it('uses raw repair bytes and the strict proposal envelope for correction and separate application', async () => {
    const repairReference = { ...reference, observation_id: 'observation-1' };
    const proposalReference = {
      ...reference,
      proposal_id: 'proposal-1',
      manifest_digest: digest('f'),
    };
    const proposal = {
      version: 1,
      proposal: {
        version: 1,
        parent_id: 'parent-1',
        proposal_id: 'proposal-1',
        manifest_digest: digest('f'),
      },
      reference: proposalReference,
      kind: 'replace_manual_prefix',
      state: 'ready',
      before_digest: digest('1'),
      after_digest: digest('2'),
      gate_completion: true,
      manual_count: 1,
      child_count: 1,
      retired_count: 0,
      rows: [],
      previous_cursor: null,
      next_cursor: null,
      coverage: {},
      omissions: [],
      actions: ['apply'],
      error_code: null,
      acknowledgement: null,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        version: 1,
        parent_id: 'parent-1',
        reference: repairReference,
        steps_digest: digest('1'),
        control_digest: null,
        raw_steps: '[{"label":"Historical","status":"completed"}]',
        raw_control: null,
        omissions: [],
        actions: ['replace_manual_prefix'],
      }))
      .mockResolvedValueOnce(response({ proposal }))
      .mockResolvedValueOnce(response({ disposition: 'applied' }));
    vi.stubGlobal('fetch', fetchMock);

    const repair = await fetchOwnedRepair('parent-1');
    expect(repair.raw_steps).toContain('"completed"');
    const page = await previewOwnedProposal('parent-1', {
      version: 1,
      kind: 'replace_manual_prefix',
      preparation_id: 'prepare-1',
      reference: repair.reference,
      prefix_json: '[{"label":"Corrected","status":"pending"}]',
    });
    expect(page.reference).toEqual(proposalReference);
    expect(await applyOwnedProposal('parent-1', {
      version: 1,
      operation_id: 'apply-1',
      reference: page.reference!,
    }, page.kind)).toBe('applied');
    // Replacement/replan are commands, not adoption. The request still carries
    // only the authoritative proposal reference and operation identity.
    expect(fetchMock.mock.calls[2][0]).toBe('/api/work-items/parent-1/owned-steps/commands');
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      version: 1,
      kind: 'replace_manual_prefix',
      preparation_id: 'prepare-1',
      reference: repairReference,
      prefix_json: '[{"label":"Corrected","status":"pending"}]',
    });
  });

  it('sends only reference operation identity stable row id and kind fields', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        results: [{ operation_id: 'confirm-1', disposition: 'applied' }],
      }))
      .mockResolvedValueOnce(response({ disposition: 'completed' }));
    vi.stubGlobal('fetch', fetchMock);

    await sendOwnedCommands('parent-1', reference, [{
      operation_id: 'confirm-1',
      step_id: 'step-1',
      kind: 'manual_confirm',
    }]);
    await finalizeOwnedSteps('parent-1', reference);

    const commandBody = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(commandBody).toEqual({
      version: 1,
      reference,
      commands: [{
        operation_id: 'confirm-1',
        step_id: 'step-1',
        kind: 'manual_confirm',
      }],
    });
    expect(JSON.stringify(commandBody.commands[0])).not.toMatch(/actor|authority|control|permit|verdict/);
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      version: 1,
      reference,
    });
  });

  it('surfaces malformed and non-JSON HTTP errors as blocking typed errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => '<html>failure</html>',
    } as Response));
    await expect(fetchOwnedSteps('parent-1')).rejects.toBeInstanceOf(OwnedStepsApiError);
  });
});
