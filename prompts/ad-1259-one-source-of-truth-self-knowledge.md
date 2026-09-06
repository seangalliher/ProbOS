# AD-1259 - One Source of Truth for Agent Self-Knowledge

**Status:** implemented against the approved amended contract; focused validation recorded below.
**Issue:** [#1309](https://github.com/seangalliher/ProbOS/issues/1309).
**Contract hash (Worker supplied):** `c2144d9ab0caf8cf3c5cc65c0be2a7866ec7699559c2491b6f6c930414c4b20d`.
**Workflow hash:** `03408b885dc3d8f0818ca2019fd8a3efd773d3f6192a6861c2e5b1709d8e8855`.
**Selected approach:** `service-owned-compatible-projections`.
**Dependencies:** preserve the shipped AD-1258 identity, domain filtering and rendering contracts.
**Test budget:** 15-25 focused behavior cases across the completed issue, strengthening existing tests.

This reconciled plan applies only to the approved issue-1309 contract. AD-1259 is already
allocated; do not allocate another AD or infer a current ceiling from this document.
All edits and checks resolve in `D:/ProbOS-burndown-b2053036-1309`, admitted at
`02826e03a5cecf8d4df807eb6d3dc212099e39d0`. Preserve dirty `D:/ProbOS`.
The Worker owns executable validation, the index, durable state, review dispatch and release.
Builder does not edit `.supervised-worker/`, run commands, stage, commit or spawn agents.

## Corrected Rationale

This is consistency consolidation, not a numeric-faithfulness security fix.
The [correcting comment 5502529668](https://github.com/seangalliher/ProbOS/issues/1309#issuecomment-5502529668)
establishes that `_check_introspective_faithfulness` ignores telemetry contents; it does not
compare the two paths' numeric values. Leave that checker unchanged.

The approved probe observed Captain trust `0.5124` versus snapshot trust `0.512`, and
inbound weight `0.8765` versus `0.88`, against unchanged shared inputs. The baseline service
collects positive inbound routing affinities and interaction breadth, whereas the Captain
also reports typed-edge inbound/outbound lists and an incident connection count. Its
positive-only, source-deduplicated routing list cannot substitute for Captain inbound data.

Worker baseline evidence for
`tests/test_ad1259_one_source_of_truth.py::test_agent_info_and_telemetry_snapshot_share_facts`:
the exact first focused command below exited 1 with **1 failed in 0.63s**, at the trust
equality assertion (`0.5124 == 0.512`). External-worktree module-origin, backend-participation
and source-unchanged checks passed before that numeric failure. This is expected regression
evidence, not post-change validation or an observation of the running vessel.
Log: `logs/gates/ad1259-baseline-crossing.log`; SHA256:
`beddac13a8875743c9beef60f058927234772d243c306d13bd4a810ff00e3160`.

## Outward Protocol Amendment

This amendment supersedes contract
`ac1512711479eeed690e9e5b06aa27ffd58d277f1fefd24e12ac34c04c4c925d`.
Retain the existing owner/caller consolidation below; do not reopen either source module.
Worker-measured **132 owner/boundary** and **145 consumer** passes are **PRE-amendment**
results. After the projection repair, the exact focused commands passed **1 crossing**, **135
owner/boundary**, and **156 consumer** cases. Evidence: `logs/gates/ad1259-frozen-crossing.log`,
`logs/gates/ad1259-frozen-owner.log`, and `logs/gates/ad1259-frozen-consumers.log`.
These recorded focused results do not attest the canonical gate, formal review, or closure.

The ledger-only contract amendment admits deterministic regeneration of
`docs/development/open-ads-report.md` from these local notes and the unchanged pinned
`docs/development/ad-ledger-snapshot.json`. The historical report is not live queue or
issue-closure evidence.

Worker reproduced M1/M2 with real collection: two peer-to-subject relations at `0.876543`
and `0.5`, plus a subject-to-peer edge at `0.42`, expose three Captain-only social keys
through `SelfQueryTool`. The unchanged exact-payload regression failed in all three variants
(omitted domains, explicit `SELF_QUERY_DOMAINS`, selected social), after module-origin,
subject and backend-participation assertions: **3 failed in 0.77s**. Log:
`logs/gates/ad1259-projection-baseline.log`; Worker-supplied SHA256:
`ee83d36de8d61456fb019e5920c2ce1432ac470e3cfbd2604ec562ea057e1370`.
Preserve the original numeric baseline above and these three real-payload cases.

In `src/probos/tools/self_query_tool.py`, after full/selected collection branches converge
and before rendering, copy the outward snapshot dictionary. For dictionary-valued social,
create a fresh dictionary retaining only existing `routing_affinities` and
`interaction_breadth` entries in their original iteration order. Preserve values, including
None, empty lists and zero; invent no defaults, validation or coercion. Leave absent or
non-dictionary social and all other domains unchanged. Render and return this projection
without mutating the returned source snapshot/domain objects or querying the graph again.

Compare Captain graph facts against a direct real service snapshot, then separately invoke
the actual tool and compare only shared trust and first-person routing/breadth facts. Require
one graph read per collection. Add small parametrized projection tests retaining the exact
returned backing snapshot/domain references and pre-call deep-copy controls, including
empty/partial/absent/non-dictionary social and selections excluding social. Preserve legacy
renderer success/error behavior and every outward envelope field. Apply prompt/tracker/test
amendments before the final source edit, then stop for immediate Worker focused validation.

## Implementation Order

### 1. Telemetry Owner and Precision

Retain the implementation in `src/probos/cognitive/introspective_telemetry.py`. Preserve the
existing async getters and snapshot/rendering interfaces; add no public getter or plumbing.

- Read `all_weights_typed()` once per `get_social_state` call and derive every graph
   projection from that collection.
- Add `incoming_affinities` and `outbound_affinities`, each a top-three list of
   `{"intent": endpoint, "weight": formatted_weight}`. Incoming uses the source endpoint;
   outbound uses the target. Include all incident typed edges, retaining different relations
   with the same endpoint and zero/negative weights. Sort by raw weight, descending, with
   stable ties, before formatting.
- `total_connections` counts each incident `(source, target, relation)` tuple once.
   A self-loop participates in both directional projections but contributes only one count.
   Foreign-agent edges do not participate.
- Preserve `routing_affinities`: positive inbound weights only, last positive entry per
   source, top three. A later nonpositive relation must not erase an earlier positive entry.
- Build the complete graph projection locally and publish its fields and count together
   only after successful collection. A successful empty graph has `total_connections=0`
   and no affinity keys. An unavailable or failed graph has no completion marker.
   Log a safe warning describing the fallback action, without raw exception payloads.
- Preserve interaction breadth as distinct intent types in the last 20 trust events.
   Event-query failure must not discard collected graph facts; interaction breadth alone
   must not imply graph availability.
- Use `probos.config.format_trust` for score, uncertainty and every emitted graph weight.
   The discriminating values must produce `0.5124`, `0.1235`, `0.8765` and `0.6543`.
   Preserve temporal rounding, trust parameters, trend calculations and
   `TRUST_DISPLAY_PRECISION`.

The owner slice and caller consolidation have PRE-amendment focused evidence. The current
repair is only the outward protocol amendment above; do not redo those earlier slices.

### 2. Normal Caller Consolidation

Retain asynchronous `_agent_info` and `_team_info` in `src/probos/agents/introspect.py`,
awaited from `act`. Preserve the other nine dispatch branches and all eleven handled intents.
The Worker direct `_agent_info`/`_team_info` usage enumeration and affected-hit reads remain
required evidence; no further caller changes are authorized by this repair. A required edit
outside `targetFiles` needs amended approval.

Use the existing public `runtime.introspective_telemetry` accessor, which returns the
startup-owned service or `None`. Do not instantiate a service in a handler, add a sync shim,
or newly access another object's private telemetry attribute. `_agent_info` reads trust
and social; `_team_info` reads trust only.

Map `trust.score` to `trust_score`, `incoming_affinities` to `hebbian.incoming_top3`
(rename `intent` to `source`), and `outbound_affinities` to `hebbian.outgoing_top3`
(rename `intent` to `target`), retaining `total_connections`. Assert exact successful
Captain output-key sets. Preserve all other agent metadata and team roster, pool, health,
summary, matching and message behavior. Do not add Hebbian fields to team rows.

Retain existing raw trust/Hebbian computations as bounded per-domain fallback for absent
service/accessor, ordinary accessor/getter errors, missing score, or unavailable Captain
graph projection. Presence, not truthiness, recognizes valid zero/empty values. Never
recompute or overwrite a valid domain because another failed, and never use the narrower
`routing_affinities` as Captain inbound data. Log sanitized failure context and fallback
action without raw exception payloads.

Handle absent registry, trust network and router explicitly. Preserve empty-registry,
unknown-agent, no-record, type-prefix, pool-name and callsign behavior. If neither service
nor raw fallback provides a required fact, use the established `success=false`/`error`
envelope rather than inventing zero connections or silently erasing data. Leave
`BaseAgent.info` and its live trust read unchanged; contain ordinary `info()` failure
honestly. Propagate `asyncio.CancelledError` and other `BaseException` lifecycle signals.

### 3. Consumer Compatibility and Documentation

After focused validation, amend only the approved affected fixtures and tests:
`tests/test_ad588_telemetry_introspection.py`, `tests/test_ad1258_self_knowledge.py`,
`tests/test_introspect.py` and `tests/test_team_introspection.py`. Await changed callsign
handlers and represent an absent service explicitly in legacy mocks where appropriate.
Amend exact collector dictionaries for additive fields without deleting assertions.
Do not alter literal renderer fixtures solely because they contain supplied three-decimal data.

Preserve `SelfQueryTool` identity authority, undeclared-subject rejection, requested-domain
filtering, permissions, feature flags, error privacy, cancellation and partial rendering.
Preserve positive-only routing rendering and empty-social rendering. Strengthen the existing
real DM, ward-room, proactive, ANALYZE and COMPOSE crossings to require four-decimal
collected values, without changing their production consumers.

Limit later `DECISIONS.md`/`PROGRESS.md` updates to AD-1259's corrected rationale,
implementation facts and genuinely obtained focused results. Finish documentation before
candidate freeze. Final shipped/closed claims and release evidence belong to the Worker,
not an unverified tracker entry or post-gate source mutation.

## Focused Validation

The crossing compares real `IntrospectionAgent.act` trust and full Captain graph facts with
a direct real telemetry snapshot. A separate real `SelfQueryTool.invoke` then compares trust
and only first-person routing/breadth under unchanged shared inputs. Assert imported module
origins, exact subjects, successful envelopes, backend participation and graph-call deltas of
one per collection. Preserve every numeric discriminator and the original trust equality
assertion. Separate injected-service authority tests must still prove both handlers consume
service results; formatting-only consolidation must not satisfy those tests.

Cover typed-edge multiplicity, nonpositive weights, raw ranking/stable ties, self-loops,
foreign edges, empty versus failed graph, absent service for both handlers, independent
domain fallback, partial metadata failure, component absence, cancellation and all eleven
dispatch routes. Use small typed `_Fake` stubs, reuse existing tests and justify uncovered
new branches. Keep source inspection distinct from execution evidence.

Worker runs these exact commands from the isolated worktree with process-scoped import
configuration selecting its `src`. Do not repoint the shared editable install or alter pytest
configuration:

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1259_one_source_of_truth.py::test_agent_info_and_telemetry_snapshot_share_facts -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1259_one_source_of_truth.py tests/test_ad588_telemetry_introspection.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1258_self_knowledge.py tests/test_introspect.py tests/test_team_introspection.py -q -n 0 -p no:randomly
```

## Acceptance and Release Gates

- Demonstrate baseline numeric failure and post-change crossing success on the correct
   source tree; record actual counts. Worker must enumerate remaining `round` calls in the
   owner and confirm none independently format trust, uncertainty or Hebbian weights.
- Prove normal service authority, unchanged Captain keys and all affected consumer
   contracts. Owner formatting alone is an intermediate slice, not completed consolidation.
- Once stable, obtain scoped independent precommit review and repair its findings before
   broad validation. Worker runs
   `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad1259-canary-b2053036`
   against the staged candidate, then locally commits the reviewed candidate so HEAD and
   index agree before the full wrapper.
- Freeze the candidate. Worker runs
   `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1259-canary-b2053036`
   synchronously without timeout, output filtering, polling, selector changes or serial
   substitution. Only the inspected supported `--receipt` option may be appended with a
   unique destination under this worktree's `logs/gates`. Require an exit-0 receipt bound to
   the unchanged commit/index and hashed manifest, JUnit and collection artifacts; bank it
   durably before cleanup, advancement or push.
- Worker verifies the required GPT-6 Astra dispatch with no fallback, and obtains formal
   `probos-diff-reviewer` review on independent Claude Opus5 after canonical success and
   installed prerequisites. Bind the formal handoff to this contract, the build report and
   the actual frozen tested/staged tree. Preliminary review cannot substitute for it.
   Repairs invalidate affected validation/review evidence and require a fresh canonical receipt.
- Push, verified issue closure, lifecycle state and campaign accounting remain Worker-owned.
   Builder reports are provisional and blocked while executable validation is pending.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do Not Build

- No new telemetry domains, new DM reachability, identity normalization, caching or
   cross-domain transactional snapshot guarantee.
- No faithfulness-checker, `TRUST_DISPLAY_PRECISION`, temporal-formatting or configuration
   changes; no dependencies, runtime/protocol expansion or `BaseAgent` refactor.
- No typed first-person graph redesign, dedicated Captain getter, duplicate raw graph query,
   further owner/introspection changes or unrelated Low-review cleanup.
- No broad private-access cleanup, UI work, adjacent audits, new AD allocation or extra issue.
- No edits outside the approved contract, dirty-main changes, live-vessel operations,
   OSS/commercial crossing, weaker governance/privacy controls or lifecycle bypass.
