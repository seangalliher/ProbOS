# Nooplex Roadmap Follow-Through

**Date:** 2026-09-07

**Status:** Planned architecture and issue ownership, requested by the Captain.
No implementation campaign, live experiment, spending, deployment, or readiness
promotion is authorized by this document. These are not ready-to-run build
prompts; reverify signatures, current behavior and affected consumers before
each bounded implementation contract.

## Purpose

Connect the [Nooplex's five capability goals](../../Vibes/Nooplex_Final.md#13-operational-definition-of-general-intelligence)
to deliverable outcomes: cross-domain transfer, long-horizon planning,
self-correction, cumulative learning and novel problem solving. Preserve the
[readiness gates](nooplex-readiness.md), rather than equating implemented
mechanisms, test counts, or agent activity with demonstrated intelligence.

The [roadmap priorities](roadmap.md#nooplex-alignment-priorities-2026-09-07)
are the delivery order. Existing platform maturity, approval, verification,
human-claim, adoption, secure-federation, team and self-maintenance issues retain
their scopes. This follow-through does not add requirements retroactively to
completed issues or enlarge AD-1270's accepted decomposition program.

## Ownership

| Decision or program | Owner | Delivery condition |
|---|---|---|
| AD-1300 Goal validity and supersession | [#1353](https://github.com/seangalliher/ProbOS/issues/1353) | Before expanding unattended consequential missions |
| AD-1301 External-effect reconciliation and compensation | [#1354](https://github.com/seangalliher/ProbOS/issues/1354) | Goal-aware integration follows AD-1300 |
| AD-1302 Derived-knowledge reassessment | [#1355](https://github.com/seangalliher/ProbOS/issues/1355) | Local contract first; federation consumer is AD-1303 |
| AD-1303 Sovereign Core Fabric pilot | [#1356](https://github.com/seangalliher/ProbOS/issues/1356) | Authenticated exchange, human claims and local reassessment first |
| AD-1304 Independent-peer conformance and exit | [#1357](https://github.com/seangalliher/ProbOS/issues/1357) | Consumes AD-1303 contract/exchange slices; required for pilot closeout |
| Protected representative Ship Trials | [AD-1186 / #1123](https://github.com/seangalliher/ProbOS/issues/1123) | Begin eligible baselines without waiting for every platform improvement |
| Cooperation research and staged emergence evidence | [#1139](https://github.com/seangalliher/ProbOS/issues/1139) | Local evidence now; stronger claims follow their own gates |
| Human knowledge lifecycle | [AD-1199 / #1136](https://github.com/seangalliher/ProbOS/issues/1136) | Bring forward alongside shared-memory validation |
| Fleet policy and sovereign membership | [AD-703 / #479](https://github.com/seangalliher/ProbOS/issues/479) | After authentication; settle policy conflicts before protected exchange |

AD-1304 depends on the parent's contract/exchange slices, not on closure of
AD-1303. AD-1303 waits for AD-1304's final evidence. AD-1302 can close its local
contract independently; AD-1303 owns the later cross-mesh correction crossing.
These distinctions avoid circular completion dependencies.

## AD-1300 Goal Validity

**Outcome:** A resumed mission still pursues a valid, authorized objective.

The inspected [CrewSessionService](../../src/probos/cognitive/crew_session.py)
already owns normalized goals/success criteria, principals, admission and
durable sessions. Extend CrewSession/WorkItem ownership, not a second goal store.
The agent judges relevance and proposes the work; the service owns revision
identity, CAS, admission and recovery under AD-1231.

- Preserve immutable goal revisions with objective, success criteria, material
  assumptions, validity/expiry conditions and authority references.
- Bind plans and consequential-action admission to the expected revision.
  Supersession closes old admission, including stale descendants.
- Revalidate after human waits, restart/resume and at consequential boundaries.
  A changed assumption triggers reassessment; unknown validity is not approval.
- Goal revision cannot grant new capabilities. Replanning retains the required
  approval and consensus. Preserve old records and frozen plan identity through
  an explicit compatibility or migration path.
- Cancellation closes new work, not history. Report already-started effects and
  unknown outcomes; AD-1301 handles their reconciliation.

**Milestone:** Real goal -> pause -> authorized revision -> restart/resume ->
action admission rejects the stale plan. Pair with an unchanged-goal control,
expiry, changed assumptions, unauthorized revision, concurrent admission,
cancelled descendants and empty/malformed input. Captain status reports what
changed, what already happened and the required decision.

**Do not build:** a central cognitive dispatcher, replacement planner,
model-authored authority override, universal cancellation guarantee, or automatic
external rollback. Coordinate with the existing plan writer and approval owners
without absorbing them.

## AD-1301 External Effects

**Outcome:** Partial success leaves an accurate account of external state and an
authorized, verified recovery path where one exists.

The inspected [CompensationHandler](../../src/probos/governance/compensation.py)
already selects recovery strategies and records reported rollback. Reuse that
vocabulary and existing mission/tool/audit owners. A recorded strategy is not
readback proof that an external action was reversed.

- Record stable operation identity before dispatch, separate attempts, expected
  goal revision, target/version preconditions, authority and evidence references.
- Keep observed outcomes separate from retry/reversal properties. Adapter-owned
  declarations distinguish retry-safe, reversible, compensatable and irreversible
  actions; model narration never supplies execution authority.
- Reconcile lost acknowledgements against the external consumer before retry.
  Unknown stays unknown when the adapter cannot establish what happened.
- Treat compensation as a new consequential action with current authority,
  consensus where required, target-state checks and verified readback.
- Preserve original effects and unrelated intervening changes. Reconcile an
  interrupted compensation just as carefully as the initial action.

**Milestone:** Through the real governed dispatch path, a deterministic local
external-service fixture receives two successful writes and then a failed step.
The permitted compensation is verified and any residual state remains explicit.
Prove the writes occurred before checking recovery. Cover commit-before-lost-ACK,
restart, denied/expired grants, irreversible effects, changed target versions,
cancellation and interruption after compensation commit.

Start with one declared compensatable effect adapter and one non-compensatable
case. New persistence must use the established connection abstraction and declare
lifecycle/recovery ownership. AD-1299 retains runtime-release promotion/rollback.

**Do not build:** a distributed transaction coordinator, second workflow engine,
arbitrary inverse-code generator, universal exactly-once/rollback guarantee, or
regression fixture that changes a live external system.

## AD-1302 Derived Knowledge

**Outcome:** Withdrawing evidence causes enrolled derived conclusions to be
reassessed, rather than silently retaining unsupported certainty.

[RecordsStore](../../src/probos/knowledge/records_store.py) already owns revisions,
classification and extensible provenance. Reuse current knowledge-edge,
episodic-correction, [erasure](../../src/probos/knowledge/erasure.py), publication
and procedure owners after enumerating their actual consumers. Completed
#1200 covers the write-claim evidence-filtering subset, not general claim
retraction. Its older AD-1255 proposal is not evidence that broad retraction
shipped. Preserve that completed subset; AD-1289/#1336 retains mission-blackboard
supersession.

- Bind a derivation to exact source revisions and distinguish independent support
  from copies of the same source.
- Authorized correction invalidates affected support and schedules bounded,
  durable, idempotent reassessment through the existing owner.
- A dependent conclusion is not automatically false. Preserve independent
  support; otherwise expose a needs-review disposition before reuse as established
  knowledge.
- Enroll explicit Records/summary retrieval and procedure-consumption paths.
  Freeze that denominator and report legacy/untracked derivations as unknown.
- Preserve history, confidentiality and unrelated valid knowledge. Do not
  automatically roll back trust, rewrite historical outputs or change grants.
- Define the disposition/update contract consumed by AD-1303; local behavior
  must not depend on federation being enabled.

**Milestone:** Versioned source -> derived summary/claim -> authorized correction
-> restart -> real retrieval reassessment. An independent-support control remains
usable; an unsupported procedure candidate is not promoted/reused without
reassessment. Exercise duplicate/out-of-order updates, cycles, fan-out bounds,
unauthorized changes, missing sources and malformed/empty dependencies.

**Do not build:** a replacement memory store, global truth authority, blanket
descendant deletion, minority-evidence suppression, model-weight unlearning or
universal remote erasure. The federation crossing belongs to AD-1303.

## AD-1303 Core Fabric Pilot

**Outcome:** A human contributes knowledge that another sovereign mesh can use,
challenge and revise through a governed, testable contract.

One bounded pilot: two separately started nodes with independent identities and
storage, one versioned claim/disposition schema and one bounded federated query.
Reuse Records/Oracle, publication, provenance, classification and federation.
Authentication remains [#1140](https://github.com/seangalliher/ProbOS/issues/1140),
human claims remain #1136, and local reassessment remains AD-1302.

1. **Contract:** negotiate schema/version, rights/provenance, partial-result and
   unknown semantics. Recipients own authorization, validation and adoption.
   Explicitly map domain vocabulary; do not compare uncalibrated embedding scores
   across unrelated spaces. Test the declared common representation or
   recipient-owned normalization/re-ranking for meaning preservation.
2. **Exchange:** human claim -> A validates/stores -> authenticated query/result
   -> B retrieves and derives an output. No shared database or hidden filesystem
   between nodes may satisfy the crossing.
3. **Revision:** disconnect B, correct A's source, reconnect B and reconcile its
   dependent conclusion without erasing independent support.
4. **Assurance:** exercise tampering/replay, policy/version conflicts, malformed
   and oversized input, denied disclosure, unavailable peers, restart and
   instruction-shaped hostile knowledge at the actual receive boundary.
5. **Evidence:** use the existing evaluation policy for matched models, goals and
   total budgets against independent-mesh aggregation and applicable single-agent
   baselines. Include tasks where cooperation is unnecessary. Record quality,
   cost, latency, human effort and partial/failure outcomes.

Knowledge remains untrusted data, not instructions or grants. A signature proves
source integrity, not truth or reputation. Repetition does not become independent
corroboration. Preserve quarantine, disputes and dissent. Pilot policy/version
conflicts must be settled before protected exchange, using AD-703's existing
owner. AD-1304 conformance is required before pilot closeout.

**Do not build:** a planetary controller, full global ontology rollout, learned
alignment research program, model-of-models scheduler, marketplace, universal
trust portability or weakened local policy for a favorable result. This pilot
does not complete every Tier C requirement or demonstrate emergence.

## AD-1304 Peer Conformance

**Outcome:** The pilot's public contract works beyond copies of ProbOS, and
participation can end without silently transferring authority.

- Publish the versioned minimal knowledge/disposition contract and valid/invalid
  vectors. State required, optional, unsupported and unknown behavior.
- Use a small independent reference peer with no imports of ProbOS runtime,
  serializers or stores. Standard cryptographic libraries remain appropriate.
- Cross real sockets with independent identities/storage, version negotiation,
  provenance, partial results and receiver-owned authorization.
- Fleet membership and policy are explicitly accepted and scoped. Neither a
  creator nor a remote administrator becomes a universal authority.
- Departure closes future admission and applicable leases. Reconcile in-flight
  and unknown effects; disconnect is not proof that nothing executed.
- Retained knowledge follows accepted rights/retention terms. Receipts distinguish
  verifiable local deletion from unreachable or unverifiable remote replicas.

**Milestone:** Independent peer exchanges, queries, challenges and corrects a
claim, then leaves. Test malformed/old/unsupported versions, replay/tampering,
wrong identity, duplicate updates, denied reads, lost acknowledgements and
departure during work. Other peers remain usable; rejoining requires fresh
admission and cannot revive expired authority. Positive controls prevent a
reject-everything peer from passing.

**Do not build:** a second full cognitive runtime, another transport stack,
universal federation constitution, public network deployment or immunity from
Byzantine/Sybil attacks merely because keys exist. Preserve legacy compatibility.

## Existing Evaluation Owners

Extend [Ship Trials / #1123](https://github.com/seangalliher/ProbOS/issues/1123),
not a replacement framework or result model:

- Protect held-out answers and final evidence from subject retrieval, codebase
  indexing, artifact search and writable workspaces. Prove isolation with an
  attempted-access fixture and a positive control. Permitted task inputs remain
  available; legitimate cumulative learning is not disabled by definition.
- Declare state isolation and allowed prior memories/learning for each arm.
  Record code/config, model identity/fallback, knowledge snapshot, rubric/goal
  hashes and total budget. Separate model upgrades and test exposure from learning.
- Keep the [targeted Sigma rig](../../prompts/archive/ad-1143-sigma-ablation-harness.md)
  as a mechanism test, with its sample-size and judge caveats. Complement it with
  representative tasks where collaboration may be unnecessary or counterproductive.
- Use independent artifact checks where available, blind judging, and explicit
  same-model-family limitations. Do not equate agreement, citations or activity
  with correctness or emergence.
- Report quality, completion, retained correction, latency, cost and human minutes
  and interruptions per verified outcome. Include failures, abandonment, required
  escalations and intervention-logging coverage. Missing effort data is unknown,
  not zero; never suppress required decisions to improve a metric.
- Treat missing, skipped, contaminated, incomparable and judge-unavailable runs
  as non-passing/inconclusive. Predeclare uncertainty and release policy.

[#1139](https://github.com/seangalliher/ProbOS/issues/1139) now owns the staged
cooperation-research plan. AD-1231's hybrid boundary remains settled and
AD-1188/#1125 stays retired. Local evidence can proceed independently of secure
federation; cross-mesh, protected longitudinal, human-panel and full-scale claims
must meet their later gates. No successful pilot is generalized into AGI.

## Common Implementation Gates

Every new public contract needs typed happy-path, edge/error and empty-input
tests where applicable, a discriminating production-consumer crossing, scoped
adversarial review and current canonical gate evidence. New APIs/UI require the
repository's specific endpoint/component tests. Use supported connection APIs,
existing Pydantic configuration and bounded lifecycle ownership. Preserve raw
Beta trust parameters and outcome-based, idempotent learning.

Planning creates no credentials or grants. Live-system access, paid experiments,
destructive operations and protected policy changes require their existing
authorization. Local deterministic fixtures must not accidentally reach production.

Verify all changes comply with the Engineering Principles in
`.github/copilot-instructions.md`.

## Allocation and Duplicate Evidence

[The canonical ceiling script](../../scripts/ad_ceiling.py) was run twice before
publication on 2026-09-07. All three sources succeeded: Git subjects AD-1299
(1,977 AD references), all-state GitHub titles AD-1299 (1,352 issues, 994 AD-titled,
below the 4,000 limit), and 61 prompt filenames at AD-1298. The prior ceiling was
AD-1299; this batch allocates AD-1300 through AD-1304 sequentially.

Authenticated `gh search issues` queries below used `--repo seangalliher/ProbOS`,
no state filter, and `--limit 100`. Every response was below the limit and every
command succeeded. Counts describe the search results, not absence of all related
runtime behavior.

| Query | Count | Disposition |
|---|---|---|
| `"goal revision"` | 0 | New goal-validity contract; reuse CrewSession and plan writer |
| `"goal validity"` | 0 | Same AD-1300 scope |
| `"goal supersession"` | 0 | Same AD-1300 scope |
| `compensation` | 2 | Closed #45 is AD-446 strategy recovery; #624 is unrelated voice work |
| `"external effects"` | 1 | #1352 retains immutable runtime-release recovery |
| `retraction` | 2 | Closed #1200 retained; #1348 is unrelated test timing |
| `"derived knowledge"` | 0 | AD-1302 adds enrolled downstream reassessment |
| `"Core Fabric"` | 1 | #1324 explicitly retains Tier A, not the new pilot |
| `conformance` | 11 | Existing ARD/standards and Worker contracts retained, not duplicated |
| `"federation exit"` | 0 | Bound to the pilot contract in AD-1304 |
| `"evaluation isolation"` | 0 | Extend #1123 and #1139 instead of creating an evaluation issue |

The conformance results were #992, #994, #1111, #1352, #1069, #989, #937, #981,
#704, #694 and #957. The current #1336 body was read: it owns typed mission
claims, supersession and dissent, not the full cross-mesh correction contract.
No additional generic echo-chamber or dissent program was created.