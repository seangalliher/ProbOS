# AD-1129 Builder Execution: Optimized EventLog Tool Protocol

**Status:** READY - prompt-only final adjudication approved 2026-07-21
**Binding specification:** `prompts/ad-1129-governed-event-log-query.md`
**Planning origin:** `e33955a8`
**Exact local base:** `3969c80b0a0f4a804a8528268f4561ca86887772` (AD-1128)
**Local ceilings:** AD-1128 / BF-673; batch commits are intentionally unpushed
**Broad backend baseline:** last measured after AD-1127: 20,032 passed / 33 skipped; context only
**Scope:** AD-1129 / #1048 only
**Code-review adjudication input bindings:** main SHA-256 `56445af59580b149ccdf5ae8b7a1d125edd71857d42c3e27707cb3bd9f2dcbdb`; execution SHA-256 `cce1c36fb61d7cd20d117052132f640b79bf89bd215fbac9160c638d8f1cced2`; base `3969c80b0a0f4a804a8528268f4561ca86887772`
**Post-adjudication binding step:** before further production or test editing, mechanically record and report amended SHA-256 plus byte length for both active prompts. Those values supersede the adjudication input hashes; any later prompt-byte change is a hard stop.
**Final-adjudication input bindings:** main SHA-256 `2b2467662ccbb5266ed3b6abbd19bde43536a7c926b49ff2c74630e78aae5ad2`; execution SHA-256 `4cfd997a080957a6fbb003c85635cd9132bd4460d261c4378c0cc3be7fa6fe30`
**Final validation input:** completed changed-surface batch `220 passed / 3 failed`; the failures are exactly the three AD-1072 delegation nodes bound below.
**Post-final-adjudication binding step:** before the one test edit or pytest run, mechanically record and report the new SHA-256 plus byte length for both active prompts. Those values supersede every earlier binding; any later prompt-byte change is a hard stop.

The main prompt is authoritative for public contracts, caps, authorization,
audit ordering, redaction, aggregate semantics, allowed files, exclusions, and
acceptance. This companion is authoritative for isolation, build order,
validation, review, and closeout.

## Final Binding Amendment - AD-1072 Delegation Authority Fixtures

This amendment has highest precedence over every conflicting build-order,
allowlist, validation, review, hard-stop, acceptance, or closeout statement
below. Preserve the entire current tree and ignore AD-1130. Production and all
completed AD-1129 tests are approved and frozen. The prior `220 passed / 3
failed` batch exposed stale AD-1072 fixtures; it does not authorize a production
fallback or a rerun of the 223-node batch.

The only non-prompt path whose current bytes may now change is:

- `tests/test_ad1072_agentic_tools.py`

Within that file, edit only `_Agent`, `_AgentRegistry`, a new narrow ontology
fixture, `_delegation_runtime`, and the authority setup strictly required by
these exact three nodes:

- `test_delegate_happy_path_returns_result_and_increments_depth`
- `test_delegate_resting_agent_still_resolves`
- `test_loop_delegate_task_runs_nested_executor_and_returns_into_transcript`

The fixture repair must satisfy the live resolver rather than bypass it:

1. Give each executor subject a non-empty exact `agent_type`; keep `pool` as
   the callsign-routing key.
2. Add `_AgentRegistry.get(agent_id)` as an exact-ID lookup returning the
   registered object or `None`, while preserving `get_by_pool` and `all`.
3. Add a concrete, fully annotated ontology fixture whose only authority API is
   `get_agent_department(agent_type) -> str | None`, backed by an explicit map
   `{"diagnostician": "medical", "counselor": "bridge"}`. Unknown types
   return `None`. Keep routing pools `bashir` and `ezri` distinct from these
   authoritative agent types.
4. Attach the complete trio to the shared delegation runtime: the existing
   registry, that ontology, and a real in-memory `TrustNetwork()`. Its default
   score is `0.5`, which resolves to `lieutenant`. A narrow deterministic
   fully annotated `get_score` object is allowed only if the real
   `TrustNetwork` is mechanically impossible, and the handback must state why.
5. The direct nested runs must exactly register Bashir with a type mapped to
   `agent_type="diagnostician"` / `medical`. The parent-loop run must exactly
   register both `ezri-1` as `agent_type="counselor"` / `bridge` and
   `bashir-1` as `agent_type="diagnostician"` / `medical`.

Do not use `MagicMock`, dynamic/phantom `SimpleNamespace` attributes,
`hasattr` authorization, private service mutation, caller `department`/`rank`
as authority, or a test-only production branch. Partial authority must remain
fail closed with `RuntimeError("agentic_identity_unresolved")`. Preserve
callsign routing, resting-agent resolution, transcript folding, nested governed
execution, and `_delegation_depth`. Do not edit the depth-guard test or counting
executor, registration-gating tests, test names, or existing behavioral
assertions except authority setup required above.

After mechanically rebinding both prompt hashes/sizes and completing this one
test-fixture repair, run only the three exact nodes together with
`-p no:cacheprovider -n 0 --timeout=90 -q --tb=short`. Then run static scope,
prompt-hash/size, whitespace, and fixture audits only. Do not run any AD-1129
test, the 223-node batch, a broader discriminator, Gate 0-4, a full suite, Git,
GitHub, tracker, archive, or AD-1130 operation.

If one of the three nodes remains red, repair only the same bound fixture
regions and rerun only those same three nodes together under `-n 0`.

## Historical Amendment - Authoritative Agentic Identity

This completed code-review amendment is preserved as audit history. The final
AD-1072 binding amendment above supersedes it for every further build-order,
allowlist, validation, review, and closeout decision. Its production and
dedicated-test results are frozen. Ignore AD-1130.

The only implementation/test paths whose current bytes may change are:

- `src/probos/cognitive/agentic_dispatch.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/cognitive/crew_executor.py`
- `src/probos/tools/delegate_task_tool.py`
- `tests/test_ad1129_eventlog_query_tool.py`

Do not further edit the EventLog implementation or any other existing AD-1129
path. The two active AD-1129 prompts are the only Architect-editable artifacts.

Implement the main prompt's exact central identity decision. In
`WorkItemAgenticExecutor.run`, resolve the exact live agent from
`runtime.registry`, resolve department from `runtime.ontology` with the
standing-orders helper fallback, and derive rank only with
`Rank.from_trust(runtime.trust_network.get_score(agent.id)).value`. Resolve one
tuple before discovery and reuse it unchanged in the reserved loop context for
invocation. No router import and no `agent.department` / `agent.rank` authority.
Fail closed with the bound stable error on any partial or invalid authoritative
surface before any tool is offered or invoked.

Retain caller `department`/`rank` only as a deprecated fallback when all three
identity services are absent and `event_log_query` is not registered. Remove
those kwargs from the two live `cognitive_agent.py` calls, the assigned-agent
`crew_executor.py` call, and the nested `delegate_task_tool.py` call. Do not
edit `crew_verifier.py`; its event-neutral projection is the intentional legacy
fallback case.

For `extra_context`, accept only the four reserved compatibility keys plus
`_delegation_depth`, `_crew_session_id`, and `_crew_work_item_id`. Merge extras
first, then overwrite `agent_id`, `department`, `rank`, and `thread_id` last
from authoritative/explicit values. Reject every other key. A forged-context
test must prove all four reserved values lose while delegation depth survives.

Extend only `tests/test_ad1129_eventlog_query_tool.py`: use a real registered
`EngineeringAgent`, call `run` without privilege kwargs, and prove the resolved
Engineering/Lieutenant identity discovers and invokes the real 61/49 query.
Also cover fail-closed and legacy fallback branches, forged reserved extras,
and exact invalid limits `-1` and `10**100`.

This code-review amendment is now historical context. The final binding
amendment above freezes those production/test repairs, requires newly amended
prompt hashes/sizes, and replaces its changed-surface batch with the exact
three-node serial validation in Section 4.

## Historical Amendment - Frozen AD-398 Identity Test

This completed test amendment is preserved as audit history and is superseded
for all further edits and validation by the final AD-1072 binding amendment
above. Its AD-398 correction is frozen.

Authorize exactly one newly added existing-test edit:
`TestNewAgentInstantiation.test_engineering_agent_attributes` in
`tests/test_ad398_crew_identity.py`. Preserve its `agent_type`, `tier`, and
non-empty `instructions` assertions. Replace only the stale three-descriptor
count and phantom-inclusive handled-intent expectations with exact proof of the
two legitimate names `engineering_analyze` and `engineering_optimize`, plus
explicit absence of `eventlog_diagnostic_query`. Do not delete or weaken the
identity test; do not add `event_log_query` to Engineering descriptors or
handled intents. Prove the governed Tool's registration and permission-filtered
discovery separately in `tests/test_ad1129_eventlog_query_tool.py`.

The third legacy `IntentDescriptor` was the phantom. It cannot be preserved as
an agent descriptor without violating #1048. Preserve the three identity
assertions (`agent_type`, `tier`, `instructions`), retain exactly two legitimate
agent intent descriptors, and cover the governed Tool as the separate third
behavioral surface.

No other function or fixture in `tests/test_ad398_crew_identity.py` may change.
That correction and its prior batch are complete and frozen. The final binding
amendment above adds only the bound AD-1072 fixture repair and exact three-node
serial validation.

## 1. Final Preflight

Treat all earlier base/HEAD, production-build, and changed-surface preflight
instructions as completed historical context. Do not invoke Git or inspect a
different prompt. Before the one authorized test-fixture edit:

1. mechanically record and report SHA-256 plus byte length for both active
   AD-1129 prompts after this final amendment;
2. freeze those prompt bytes; any later prompt mutation is a hard stop;
3. confirm the only newly authorized non-prompt path is
   `tests/test_ad1072_agentic_tools.py`; and
4. preserve every production, dedicated AD-1129 test, tracker, archive, and
   AD-1130 byte.

The supplied final-adjudication input hashes identify the reviewed input only;
do not reuse them as post-amendment bindings.

## 2. Build Once, Then Test

All AD-1129 production and dedicated-test work is complete and frozen. Before
pytest, edit only the bound authority fixtures in
`tests/test_ad1072_agentic_tools.py`:

1. add exact `agent_type` identity and exact-ID registry lookup;
2. add the protocol-faithful explicit-map ontology fixture;
3. attach the complete registry/ontology/real-TrustNetwork trio to the shared
   delegation runtime; and
4. ensure the exact parent and delegate subjects used by the three bound nodes
   are registered and represented in the ontology map.

Finish that one test-fixture edit before invoking pytest. Do not edit
production, dedicated AD-1129 tests, depth/registration tests, trackers, or
prompt archives. Do not run a baseline, Gate 0-4, UI tests, or a full backend
suite.

## 3. Static Scope Audit Before Pytest

Before pytest, confirm the new repair diff is confined to the bound fixture
helpers and three-node authority setup in `tests/test_ad1072_agentic_tools.py`.
Check:

- every nested or parent executor subject has exact registry identity, a
  non-empty exact `agent_type`, an explicit ontology department, and live
  `TrustNetwork.get_score` authority;
- `_AgentRegistry.get` is an exact lookup returning an object or `None`;
- the ontology fixture has one fully annotated method and no dynamic fallback;
- no `MagicMock`, phantom attribute, private service mutation, or caller/agent
  department/rank authority was introduced;
- no production, dedicated AD-1129 test, AD-398, AD-664, depth-guard,
  registration-gating, tracker, archive, or AD-1130 path changed; and
- delegation behavior, callsign/liveness resolution, transcript folding, and
  depth assertions are byte-preserved outside strictly necessary setup.

Fix only defects inside those bound fixture regions before running tests.

## 4. Three-Node Serial Validation

Run exactly these three nodes together after the fixture repair is complete:

```powershell
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1129_ad1072_serial_' + $gateId)
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest `
      'tests/test_ad1072_agentic_tools.py::test_delegate_happy_path_returns_result_and_increments_depth' `
      'tests/test_ad1072_agentic_tools.py::test_delegate_resting_agent_still_resolves' `
      'tests/test_ad1072_agentic_tools.py::test_loop_delegate_task_runs_nested_executor_and_returns_into_transcript' `
      -p no:cacheprovider -n 0 --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Record exact passed/skipped/warning counts and exit code. A failure authorizes
only a minimal repair in the same bound AD-1072 fixture regions followed by a
rerun of these same three nodes together under `-n 0`.

Do not run the prior 223-node batch, an AD-1129 node, another focused set, a
blast/baseline/full gate, or a per-AD additive equation. The historical 20,032
/ 33 broad baseline and `220 passed / 3 failed` batch are context, not totals
to recompute.

## 5. Builder Evidence Package

Return the still-uncommitted tree for Architect implementation review with:

- the two mechanically rebound active-prompt SHA-256 values and byte lengths;
- the exact three node IDs, passed/skipped/warning counts, duration, and exit
   code from the one `-n 0` run;
- exact fixture evidence that `_AgentRegistry.get` returns by ID, ontology maps
   each subject's exact type, and real `TrustNetwork.get_score` supplies rank;
- proof that the parent run registers Ezri and Bashir, both direct nested runs
   register Bashir, resting-agent resolution remains intact, and nested context
   still carries `_delegation_depth == 1`;
- proof that no `MagicMock`, phantom authority attribute, production fallback,
   depth-test change, dedicated AD-1129 test change, or other path was added;
   and
- static scope/whitespace audits plus hash/size evidence for the final dirty
   files, without invoking Git.

Do not stage, commit, update trackers, archive prompts, push, or mutate GitHub
before the Architect returns `APPROVED`.

## 6. Architect Review Decision

Architect reviews in this order:

1. **Scope:** only the bound AD-1072 fixture/helper setup changed after this
   final prompt amendment; no production, dedicated AD-1129 test, or AD-1130
   mutation.
2. **Contract/security:** each executor subject has exact registry, ontology,
   and trust authority; partial authority remains fail closed; no caller or
   agent rank/department fallback was introduced.
3. **Evidence:** the exact three serial nodes pass, delegation behavior/depth
   remain preserved, and static audits show no mock/phantom or wider edit.

Any Required finding returns only to the same fixture regions and same
three-node serial run. No changed-surface or full suite is authorized. Closeout
begins only after an explicit `APPROVED` implementation verdict.

## 7. Static Closeout After Approval

1. Keep both active prompt files at their mechanically rebound final hashes.
2. Re-run static scope/hash/size/whitespace/fixture audits only; do not rerun
   pytest.
3. Report the approved one-file fixture delta and exact three-node result.
4. Do not stage, commit, push, call GitHub, update trackers, archive prompts, or
   begin AD-1130 work under this handback.

## Hard Stops

- Base differs from exact local AD-1128 HEAD, or the build relies on/touches
   CrewSession ingress beyond the direct `runtime.py` EventLog injection.
- Tool needs DB path/concrete EventLog/SQL/file/network/runtime/API/private state,
   or caller input influences SQL structure.
- Audit leaks values/timestamps/rows/data/detail/SQL/exceptions/query/result.
- Discovery/registry/Tool auth disagree or caller context can elevate identity.
- Live execution reads caller/agent department or rank instead of exact
   registry/ontology/trust authority; identity is resolved twice; partial
   authority falls back; or EventLog registration is reachable in legacy mode.
- `extra_context` accepts an unbound key, overwrites a reserved key, or loses
   `_delegation_depth` / crew private state.
- Aggregate is generic/unbounded/not exact 61/49, or cancellation is normalized.
- Any endpoint, agent/pool, config/YAML, schema/index, EventType, dependency,
   trust/metrics/notifier/UI, AD-1130+, or unauthorized path is needed.
- Any deletion/weakening of AD-398 Engineering identity assertions, any
   reintroduction of the phantom, any teaching of `event_log_query` as an agent
   intent, or any other AD-398 test/fixture edit.
- Any tracker edit, prompt archive move, broad gate, push, or GitHub mutation
   occurs before AD-1133.
- Any production/dedicated AD-1129 test change, any edit outside the bound
   AD-1072 fixture regions, or any rerun of the 223-node batch occurs.
- Any of the three serial nodes remains red, changed paths warn, or review is
   not `APPROVED`.

## Acceptance

- Main prompt acceptance is satisfied exactly.
- The frozen AD-398 Engineering identity test preserves agent type, tier,
  instructions, and the two legitimate Engineering intent names while
  explicitly rejecting the phantom; governed Tool discovery is proven in the
  AD-1129 test surface.
- The completed changed-surface result remains recorded as `220 passed / 3
   failed`; it is not rerun. After fixture repair, the exact three AD-1072 nodes
   pass together under `-n 0`.
- A real registered Engineering agent obtains 61/49 without injected privilege;
   missing/partial authority fails closed, the exact legacy fallback remains
   event-log-free, forged extras lose, delegation depth survives, and limits
   `-1` / `10**100` are invalid.
- AD-1072 delegation fixtures provide exact registered identities,
   protocol-faithful ontology, and live trust for both parent and target while
   preserving resting-agent and depth behavior.
- No AD-1129 test, changed-surface batch, additional test gate, additive
   full-gate equation, baseline/full suite, or push runs before AD-1133.
- Closeout is static-only: no Git, GitHub, tracker, archive, or AD-1130
   operation occurs under this handback.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prompt Review Record

**READY.** Main-prompt Pass 1 approved the exact local AD-1128 rebase and scope;
Pass 2 approved the typed/bounded/redacted authorization and audit contract;
Pass 3 approved all-code-before-tests, one optimized changed-surface batch,
Architect review, active-prompt local-only closeout, exact commit subject, and
AD-1133 tracker/archive/broad-gate/push deferral.

### Adjudication Pass 1 - Continuation scope (2026-07-21)

**Verdict: APPROVED.** Preserve the partial live implementation. Authorize only
the frozen AD-398 Engineering identity function; no other AD-398, test, source,
tracker, or execution surface is added.

### Adjudication Pass 2 - Identity and governed discovery (2026-07-21)

**Verdict: APPROVED.** Retain agent type, tier, instructions, and the exact two
legitimate Engineering intents. Keep the phantom absent and prove
`event_log_query` only through ToolRegistry/agentic discovery coverage.

### Adjudication Pass 3 - Batch readiness (2026-07-21)

**Verdict: APPROVED.** The AD-398 file joins the allowlist and sole changed-
surface batch. Coding remains first; validation remains one
`-n 16 --dist=worksteal` batch. Builder must mechanically bind both amended
prompt hashes and sizes before continuation.

### Code-review Adjudication Pass 1 - Authority and repair scope (2026-07-21)

**Verdict: APPROVED after required correction.** Freeze the existing EventLog
and completed AD-1129 surfaces. Repair only four production files and the
AD-1129 test file; ignore AD-1130 and preserve all other live bytes.

### Code-review Adjudication Pass 2 - Identity and context security (2026-07-21)

**Verdict: APPROVED after required correction.** Exact registered identity,
ontology plus standing-orders fallback, and trust-derived Rank produce one
tuple for discovery and invocation. Legacy privilege is restricted to the
no-resolver/no-EventLog case. Extras merge first; all reserved values overwrite
last; bounded delegation/crew state survives.

### Code-review Adjudication Pass 3 - Bound execution (2026-07-21)

**Verdict: APPROVED.** Real registered Engineering 61/49 execution, authority
failure/fallback, forged reserved context, and exact `-1` / `10**100` limits are
binding regressions. Run only the amended scoped `-n 16 --dist=worksteal`
batch. Mechanically report final prompt hashes/sizes before continuation.

### Final Adjudication Pass 1 - Failure classification (2026-07-21)

**Verdict: PRODUCTION APPROVED; TEST FIXTURE REPAIR REQUIRED.** The completed
changed-surface batch reported `220 passed / 3 failed`, with all failures in the
three exact AD-1072 delegation nodes. Their shared runtime supplies registry
without ontology/trust, so the AD-1129 resolver correctly fails closed.

### Final Adjudication Pass 2 - Fixture authority and scope (2026-07-21)

**Verdict: APPROVED after binding correction.** Authorize only the shared
AD-1072 fixture/helper regions and exact three-node setup. Require exact-ID
registry lookup, explicit-map ontology, real in-memory trust, and exact parent
plus target registration. Production fallback weakening and mock/phantom
authority are forbidden.

### Final Adjudication Pass 3 - Serial readiness (2026-07-21)

**Verdict: READY.** Mechanically rebind both prompt hashes/sizes, run only the
three exact nodes together under `-n 0`, and finish with static audits. Do not
rerun the 223-node batch, any AD-1129 node, broad gates, Git/GitHub, trackers,
archives, or AD-1130 work.