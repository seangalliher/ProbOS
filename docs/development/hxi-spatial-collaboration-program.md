# HXI Spatial Collaboration Program

Status: planned, issue-backed; not implemented or activated. Parent program:
[AD-1307 / #1360](https://github.com/seangalliher/ProbOS/issues/1360). GitHub
issues and their release evidence remain the completion authority. This program
does not promote a Nooplex readiness tier or start a build campaign.

## Product contract

ProbOS is a workspace in which people and autonomous crew collaborate on work,
not a chat interface for selecting tools. A new user should be able to ask a simple
question immediately, or develop a complex objective with the crew, without first
learning the ship's implementation taxonomy.

The experience should be futuristic, beautiful, engaging, and authentically
digital. Spatial relationships, light, motion, voice, and persistent context should
communicate actual collaboration. They must not hide work, fabricate progress, or
make the user arrange windows before obtaining a result.

Preserve the luminous agent orbs, departmental relationships, visible connections,
and direct access to collaborators. The surrounding menus, forms, navigation,
foreground work, and recovery paths may change substantially. The mesh remains
the recognizable spatial environment, not decoration behind a conventional
dashboard.

## Architectural boundaries

- Agents are collaborators with identity, expertise, memory boundaries, initiative,
  and accountable contributions. Tools are instruments those agents may use.
- The human can contribute evidence, edit an artifact, challenge a claim, refine an
  objective, or request help. Collaboration is not reduced to approving commands.
- Preserve AD-1231: agents decide what work matters, whether to take it, and how to
  reason; deterministic services own durable ordering, admission, recovery, and
  exactly-once effects. The HXI must not become a central cognitive dispatcher.
- Project existing room, task, artifact, knowledge, and authority identities into
  the workspace. Do not introduce a second task engine, memory store, approval
  inbox, or server state authority for the UI.
- Desktop, mobile, and eventual immersive views must share semantic objects and
  commands. Screen coordinates, ray hits, gaze, or visual proximity never grant
  authority or decide which agent should think.
- Spatial readiness begins with stable object identity, explicit selection and
  focus, coordinate-independent actions, reversible presentation layout, privacy,
  and accessible input alternatives. It does not require shipping VR before a
  dependable desktop experience.
- Preserve consensus, authorization, audit, knowledge classification, sovereign
  memory, and compatibility. A denial should offer a governed path where one
  exists, not a bypass or an invented claim of completion.

## Evidence and design authorities

- [Live HXI review](hxi-live-ux-review-2026-09-07.md): 24 measured or explicitly
  qualified issue candidates, working capabilities, and untested boundaries.
- [Original Glass Bridge design](../design/hxi-glass-bridge.md): the mesh stays;
  current work is foregrounded; decisions rise; input and return paths stay usable.
- [Repository principles](../../.github/copilot-instructions.md): agent-native
  hybrid coordination, governance, HXI, tests, and release obligations.
- [Roadmap](roadmap.md): existing programs and work ownership.
- [Nooplex readiness](nooplex-readiness.md): evidence tiers are not advanced by
  this experience-planning exercise.

Local planning hypothesis: the reviewed capabilities can become a coherent
experience by repairing their real producer-to-consumer paths and introducing a
shared spatial presentation contract over existing authorities, rather than
replacing the mesh or copying a terminal/chat product.

The discriminating acceptance journey is: a new user identifies the crew, asks a
simple question, opens a bounded multi-person room, shares a real input, develops
and revises work with the crew, handles a governed blocker, receives a verified
artifact, and resumes the same work after reconnect. The desktop and accessible
input paths must complete that journey before immersive claims are made.

## Experience decisions

### Collaborators, work objects, and instruments

The primary spatial objects are collaborators, purposes, ongoing work, evidence,
artifacts, questions, and decisions. A conversation is one view of that work.
Tools and workstations are instruments within the context, not substitutes for
the agents or the whole application model.

Reuse existing identities for crew, room/project, CrewSession/WorkItem, artifact
revision, Records entry, mission-blackboard entry and approval. Presentation
references may expose those identities through a typed, versioned view contract;
they must not become a second durable authority. A view's geometry, selection,
focus, pinning and camera are presentation state. Layout recovery cannot delete
work, grant permissions, change task status or expose another scope's content.

People can contribute a source, revise a document, challenge an assertion, refine
an objective, or ask for help. Preserve human versus agent provenance. Neither
visually adjacent objects nor a majority of agreeing avatars establish truth.
Agents retain instructions-first cognition and the existing governance paths;
the presentation host does not rank which agent should think about the work.

### A light beginning and progressive complexity

A new user enters a usable workspace, sees crew identity and a clear input, and
can ask immediately. Do not make a marketing landing page, mandatory tour, tool
picker or formal project setup the first interaction. Genuine installation,
provider and readiness prerequisites remain visible and owned by existing setup
work; do not imply that a configured-off feature is ready.

A simple request can remain a single exchange. Complex work grows a shared brief
through conversation: objective, inputs, collaborators, constraints, success
evidence, deliverable and authority. The user reviews the meaningful decisions,
not three redundant forms or a sequence of implementation statuses. Clarification
is contextual; no blanket complexity classifier or compulsory multi-agent room.

Resume and New conversation are different actions. A new transcript does not
erase sovereign memory. The interface identifies recipient, room/project scope,
retained context, and whether input is a draft or an authorized request. Behavioral
plan/execute mechanics stay with AD-1156; goal revisions stay with AD-1300.

### One spatial workspace, several compatible views

Keep the mesh's orbs, learned connections, department organization and direct
selection. Work comes forward in a consistent spatial layer rather than a pile
of independently positioned forms. On desktop, default to one primary work area
and contextual detail, with deliberate pinning/comparison for expert work. Do not
require manual resizing or window placement for the first successful task.

Use stable navigation and the existing searchable palette for crew, conversations,
work, knowledge, Bridge attention and settings. These are destinations into one
workspace, not separate applications. User-facing labels will be tested; preserve
ship/department names as context without requiring familiarity with them.

Phone and tablet views project the same objects into reachable single-column or
adaptive layouts. CompactApp and MobileShell are real consumers, not merely small
desktop screenshots. The future XR view projects the same semantic selections
and actions into spatial interaction. It is not a texture of today's desktop
forms and not a second execution system.

### Glass material, contextual behavior

AD-1202's accepted choice is **primitives plus one complete Bridge exemplar**.
Glass supplies material and depth; LCARS supplies attention-driven behavior.
Use precise geometry, geometric-sans human text, monospace technical detail,
legible contrast, restrained translucency, and state-bearing light/motion. Preserve
the existing mesh palette and HXI stroke-SVG conventions.

Define coherent transitions for arrival, selecting a collaborator, a contribution,
work beginning, an artifact arriving, a blocker, verification, completion and
return. Each expressive state must be grounded in actual runtime evidence or
explicitly pending/unknown. No simulated thought stream, fabricated progress,
decorative activity, or celebration before a result is verified.

Spatial continuity matters more than visual spectacle: preserve selected crew,
task identity, useful placement, camera orientation and the route back. Separate
actual routing edges from presentation tethers or proposed collaborations.
Reduce bloom locally behind reading without replacing the mesh. Reduced motion
must retain every action and state. Sound remains preference/consent controlled.

### Authority remains explicit

Bridge leads with Needs you, Active work and Recent results. A notification opens
the exact task/room; acknowledgement is not resolution. Approval is not navigation
or a side effect of looking at an object. Existing decision identities, scope,
expiry and reconciliation remain shared across inline and Bridge surfaces.

Preserve the Captain's confirmed #1166 decision: a scoped action standing rule
authorizes a future re-decided attempt; it does not replay a stale browser action.
Change of goal, collaborator or device never silently widens authority. Cancellation
stops permitted future work but does not claim that past/unknown effects vanished.

Separate inspection from permission editing, qualification from effective access,
and trust from service readiness. Clinical/private data and sovereign memory retain
their access boundaries. A graceful unavailable state cannot conceal a defect.

## Delivery register

All entries are planned. Numbers identify decisions, not shipped capability.

| AD | Outcome | Primary issue | Dependency boundary |
| --- | --- | --- | --- |
| AD-1307 | Program, collaborator-first design contract and release acceptance | [#1360](https://github.com/seangalliher/ProbOS/issues/1360) | Integrates the slices below; no second runtime authority |
| AD-1308 | Spatial workspace host and semantic navigation | [#1363](https://github.com/seangalliher/ProbOS/issues/1363) | AD-1202 primitive slice; existing workspace/host identities |
| AD-1309 | Progressive intake and explicit conversation context | [#1362](https://github.com/seangalliher/ProbOS/issues/1362) | AD-1308 host slice; existing modes, goal revision and live-progress owners |
| AD-1310 | Shared evidence and artifact handback canvas | [#1361](https://github.com/seangalliher/ProbOS/issues/1361) | AD-1308; input/execution repairs; human-claim/blackboard contracts for the typed-evidence slice |
| AD-1311 | Embodied co-presence and explicit multimodal sessions | [#1364](https://github.com/seangalliher/ProbOS/issues/1364) | AD-1308, AD-1202 and avatar stability; existing streaming/media owners |
| AD-1312 | Contextual crew, knowledge and administration | [#1366](https://github.com/seangalliher/ProbOS/issues/1366) | AD-1308, AD-1202; existing effective-authority, evidence and approval APIs |
| AD-1313 | Authentic digital visual language and spatial continuity | [#1365](https://github.com/seangalliher/ProbOS/issues/1365) | AD-1202 tokens and real AD-1308/1310/1311 projections |
| AD-1202, existing | Shared controls and complete Bridge exemplar | [#1142](https://github.com/seangalliher/ProbOS/issues/1142) | Exemplar may use current public navigation; no dependency on completing AD-1308 |
| AD-721c, existing | Bounded WebXR collaboration pilot | [#530](https://github.com/seangalliher/ProbOS/issues/530) | Ready AD-1308/1310/1311/1313 contracts and declared headset validation |

AD-1308 can consume AD-1202's independently validated primitive slice before its
entire adoption is complete. AD-1202's Bridge exemplar can use the existing public
opening actions, so these two items must not wait for each other's closure.
The same rule applies to other explicit contract-slice dependencies: a consumer
starts on a verified compatible contract, never a fictional future API.

### AD-1308: Spatial host

Extend the existing workspace registry/host with stable semantic references,
selection, focus, reveal, open/return and intent actions. Route orb selection,
navigation, palette, deep links and notifications through one initialized
destination path. Migrate one real room first, then the remaining full/compact/
mobile hosts. Version presentation state and preserve old routes/drafts/context.

Acceptance crosses multiple real entry points into the same object and back,
with no stale hydration, lost draft, offscreen focus or authority derived from
coordinates. Do not introduce a server task store, new cognitive dispatcher,
renderer replacement, headset runtime or unused abstract registry.

### AD-1309: Progressive collaboration

Unify simple exchange, explicit fresh/resumed conversation and progressively
briefed work. The proposed typed interaction intent distinguishes response-only,
planning and authorized execution, consuming AD-1156 mode semantics rather than
duplicating them. Slow-turn continuation retains one run and result identity;
no cancel-and-redispatch to manufacture an acknowledgement. AD-1193 streaming
and AD-1174 progress remain separate owners.

Acceptance requires both the no-ceremony simple task and a complex revised
objective with meaningful consent, current goal revision, bounded continuation,
honest cancellation and restart/reconnect. A new thread is never advertised as
erasing memory. Do not parse arbitrary prose into new security semantics.

### AD-1310: Shared evidence and handback

Expose task-linked inputs, artifact revisions, claims, evidence, questions, dissent
and decisions through existing data owners. Start with real input -> artifact ->
preview/edit -> governed save -> handback -> agent read of that exact revision.
Then consume AD-1199 human claims and AD-1289 mission-blackboard contracts,
including AD-1289's existing AD-1286 dependency. Do not implement parallel claim
records while waiting for those dependencies.

Accept a human challenge and revised artifact without overwriting history or
private memory. Guard version conflicts, classification, cross-room references
and malformed/oversized content. Consulted evidence is not proof that an external
effect succeeded. Reuse safe declarative A2UI where appropriate; agent-authored
forms do not gain arbitrary script execution or decision authority.

### AD-1311: Embodied sessions

Unify participant identity, speaker/contribution state, captions, input/output
devices, capture mode and End/return. Separate microphone, speaker, camera,
screen, recording and ambient sensing consent. A call releases only its owned
resources; independent ambient sensing cannot be silently misrepresented as off.
Distinguish typed, dictated and explicitly enabled open-conversation input.

Accept actual speech -> transcript -> intended recipient -> reply -> playback ->
terminal state, plus failures, interruption, supersession, device loss and
reconnection. Preserve per-participant voice and no-history-replay behavior.
Hardware accuracy/privacy/comfort evidence is distinct from media-event tests.
No default raw recordings, gaze/pose retention or second media engine.

### AD-1312: Contextual management

Lead with a collaborator's identity, expertise, availability, current work and
attributable contributions. Distinguish effective capability, permission,
qualification, proficiency, readiness and unmeasured research signals. Coordinate
with existing authority/wellness/qualification/maturity owners; do not reimplement
their engines or infer that no explicit grant means incapable.

Unify knowledge search/read/filter context while keeping privacy and service
availability honest. Use contextual settings links, labeled adaptive fields and
explicit save/impact state. Preserve inline/Bridge decision reconciliation and
scoped standing-rule semantics. No new approval inbox, enterprise-only management
feature or automatic enabling of optional integrations.

### AD-1313: Visual and spatial continuity

Make the shared semantic states feel like one environment: consistent typography,
depth, focus, motion, participant cues, artifact arrival and attention. Deliver an
integrated production journey plus bounded adoption, not a static style guide or
screenshot-only scene. Preserve orbs/connections and camera context; visually
differentiate evidence, current action, proposal and unknown state.

Measure readability, input response, frame behavior and reduced-motion parity on
declared devices. Initial engineering targets are local action feedback within
100 ms and stable 60 Hz desktop motion under the declared supported scene load;
they are proposed acceptance budgets, not measured current performance. Provider
latency is reported separately. No decorative progress, compulsory sound,
gaze-driven scheduling, unrelated avatar-generation pipeline or mesh replacement.

## Focused repair register

These issues are children of #1360 and can ship independently of the host redesign.
They do not allocate additional AD numbers. Every uncertain cause must be
reproduced before a build selects a mechanism; the report's caveats are retained.

| Repair | Issue | Priority | Discriminating result |
| --- | --- | --- | --- |
| Foreground geometry and drawer/launcher interference | [#1369](https://github.com/seangalliher/ProbOS/issues/1369) | High | Actual composer/Send/Close hit targets fit at supported sizes |
| Fresh, scoped agent telemetry | [#1370](https://github.com/seangalliher/ProbOS/issues/1370) | Medium | Same identity/time/scope agrees; legitimate different populations are labeled |
| Readiness versus empty/failed views | [#1368](https://github.com/seangalliher/ProbOS/issues/1368) | Medium | 503/disabled/denied are not empty data or healthy capability |
| Avatar telemetry/render lifecycle | [#1367](https://github.com/seangalliher/ProbOS/issues/1367) | High | Bounded subscriptions and correct rendered participant after mic/room changes |
| Group message reconciliation | [#1372](https://github.com/seangalliher/ProbOS/issues/1372) | High | One persisted message renders once in either HTTP/event ordering |
| Input reference through actual agent read | [#1371](https://github.com/seangalliher/ProbOS/issues/1371) | High | Uploaded CSV yields discriminating IDs, scoped provenance and correct name/readiness |
| Native crew worker identity/admission | [#1374](https://github.com/seangalliher/ProbOS/issues/1374) | High | Eligible work produces a result; unresolved authority blocks usefully without bypass |
| Failure notification opens its exact work | [#1373](https://github.com/seangalliher/ProbOS/issues/1373) | High | Badge -> notification -> room/task; acknowledgement is not resolution |
| Canonical task state in every projection | [#1375](https://github.com/seangalliher/ProbOS/issues/1375) | High | One failed identity is failed in API, room, board, detail and Bridge |
| Coherent global answer from redundant results | [#1378](https://github.com/seangalliher/ProbOS/issues/1378) | Medium | Equivalent results yield one answer without deleting disagreement/evidence |
| Recreation opponent-turn progression | [#1376](https://github.com/seangalliher/ProbOS/issues/1376) | Medium, optional | Real opponent acts and game terminates, or bounded failure/forfeit is explicit |
| Public managed-browser end lifecycle | [#1377](https://github.com/seangalliher/ProbOS/issues/1377) | Medium | End selected session releases its resources without deleting other work/recordings |

Browser End session is a bounded new lifecycle affordance, not proof an existing
close endpoint is broken. Equivalent global-answer aggregation is separate from
duplicate group rendering. Input arrival after refresh does not invalidate the
measured failed agent-read task, nor prove permanent data loss. A missing opponent
turn and a solid avatar image are observations, not established root causes.

## Review-to-owner coverage

One primary owner per finding. Secondary integrations are not alternative
closure owners or permission to count a partially delivered path twice.

| Finding | Primary owner | Secondary integration |
| --- | --- | --- |
| UX-01 | [#1369](https://github.com/seangalliher/ProbOS/issues/1369) | AD-1308 host adoption |
| UX-02 | [AD-1309 / #1362](https://github.com/seangalliher/ProbOS/issues/1362) | Existing default DM/thread compatibility |
| UX-03 | [#1370](https://github.com/seangalliher/ProbOS/issues/1370) | Completed AD-1259 and contextual crew views |
| UX-04 | [AD-1309 / #1362](https://github.com/seangalliher/ProbOS/issues/1362) | AD-1193 streaming, AD-1174 progress |
| UX-05 | [#1368](https://github.com/seangalliher/ProbOS/issues/1368) | Existing maturity/doctor contracts |
| UX-06 | [AD-1202 / #1142](https://github.com/seangalliher/ProbOS/issues/1142) | Safe rich content and AD-1313 visual adoption |
| UX-07 | [AD-1311 / #1364](https://github.com/seangalliher/ProbOS/issues/1364) | Existing media/streaming owners |
| UX-08 | [#1367](https://github.com/seangalliher/ProbOS/issues/1367) | AD-1311 sessions; AD-721c pilot prerequisite |
| UX-09 | [#1372](https://github.com/seangalliher/ProbOS/issues/1372) | All transcript hosts and speech consumers |
| UX-10 | [#1371](https://github.com/seangalliher/ProbOS/issues/1371) | AD-1310 handback |
| UX-11 | [#1374](https://github.com/seangalliher/ProbOS/issues/1374) | AD-1309/1310 work journey |
| UX-12 | [AD-1309 / #1362](https://github.com/seangalliher/ProbOS/issues/1362) | AD-1308 layout; AD-1310 work objects |
| UX-13 | [AD-1308 / #1363](https://github.com/seangalliher/ProbOS/issues/1363) | Current-route repairs can land first |
| UX-14 | [#1373](https://github.com/seangalliher/ProbOS/issues/1373) | Existing inline approval owner remains separate |
| UX-15 | [#1375](https://github.com/seangalliher/ProbOS/issues/1375) | No second WorkItem lifecycle |
| UX-16 | [#1368](https://github.com/seangalliher/ProbOS/issues/1368) | AD-1312 knowledge/admin states |
| UX-17 | [AD-1308 / #1363](https://github.com/seangalliher/ProbOS/issues/1363) | AD-1309 novice entry; AD-1313 continuity |
| UX-18 | [AD-1312 / #1366](https://github.com/seangalliher/ProbOS/issues/1366) | Existing maturity/qualification/evidence owners |
| UX-19 | [AD-1312 / #1366](https://github.com/seangalliher/ProbOS/issues/1366) | AD-1202 fields; existing approval semantics |
| UX-20 | [AD-1310 / #1361](https://github.com/seangalliher/ProbOS/issues/1361) | Existing workstation/ArtifactStore APIs |
| UX-21 | [#1378](https://github.com/seangalliher/ProbOS/issues/1378) | Distinct from UX-09 delivery reconciliation |
| UX-22 | [AD-1202 / #1142](https://github.com/seangalliher/ProbOS/issues/1142) | AD-1308 host and AD-1312 form migration |
| UX-23 | [#1376](https://github.com/seangalliher/ProbOS/issues/1376) | Optional recreation, not a required work engine |
| UX-24 | [#1377](https://github.com/seangalliher/ProbOS/issues/1377) | AD-1310 workstation lifecycle |

The user's positive goals beyond individual defects have explicit owners:
collaborator-first contract AD-1307, spatial semantics AD-1308, novice/simple/complex
entry AD-1309, human contribution AD-1310, presence AD-1311, contextual forms
AD-1312/AD-1202, beauty/engagement/continuity AD-1313, and real VR AD-721c.

## Existing owners retained

| Owner | Reused contract and scope |
| --- | --- |
| [AD-1202 / #1142](https://github.com/seangalliher/ProbOS/issues/1142) | Tokens, accessible controls, safe content and one Bridge exemplar; not another full HXI program |
| [AD-1156 / #1083](https://github.com/seangalliher/ProbOS/issues/1083) | Behavioral planning/execution modes; no new suspended-loop gate |
| [AD-1193 / #1130](https://github.com/seangalliher/ProbOS/issues/1130) | Safe streaming transport and partial-text semantics; structured tool execution stays guarded |
| [AD-1174 / #1105](https://github.com/seangalliher/ProbOS/issues/1105) | Real live progress in every active shell |
| [AD-1243 / #1236](https://github.com/seangalliher/ProbOS/issues/1236) | Consulted-evidence affordance outside reply prose/TTS |
| [AD-1199 / #1136](https://github.com/seangalliher/ProbOS/issues/1136) | Human epistemic provenance, consent, revision, challenge and erasure |
| [AD-1289 / #1336](https://github.com/seangalliher/ProbOS/issues/1336) | Typed mission blackboard; keep AD-1286/#1333 prerequisite and existing parent |
| [AD-1300 / #1353](https://github.com/seangalliher/ProbOS/issues/1353) | Durable goal revisions and supersession |
| [AD-1212 / #1166](https://github.com/seangalliher/ProbOS/issues/1166) | Inspectable action payload and scoped standing-rule-only future attempts |
| [AD-1213 / #1170](https://github.com/seangalliher/ProbOS/issues/1170) | Chain-of-command authority in the approval path |
| [AD-1216 / #1175](https://github.com/seangalliher/ProbOS/issues/1175) | Same decision from inline/Bridge surfaces, shared reconciliation |
| [AD-1261 / #1311](https://github.com/seangalliher/ProbOS/issues/1311) | Effective authority domain, distinct from new AD-1311 media design |
| [AD-1260 / #1310](https://github.com/seangalliher/ProbOS/issues/1310) | Wellness-domain boundaries, distinct from new AD-1310 work canvas |
| [AD-1287 / #1334](https://github.com/seangalliher/ProbOS/issues/1334) | Evidence-bound qualification, not inferred from UI labels |
| [AD-1242 / #1234](https://github.com/seangalliher/ProbOS/issues/1234) and [AD-1245 / #1238](https://github.com/seangalliher/ProbOS/issues/1238) | Actual verifier evidence and judged/refused/unavailable distinctions |
| [AD-1305 / #1358](https://github.com/seangalliher/ProbOS/issues/1358) and [AD-1306 / #1359](https://github.com/seangalliher/ProbOS/issues/1359) | Group write evidence and mixed-write truth; not duplicated by input-read repairs |
| [AD-1186 / #1123](https://github.com/seangalliher/ProbOS/issues/1123) | HXI journey pack and release/usability evidence on the existing trial framework |
| [AD-1270 / #1324](https://github.com/seangalliher/ProbOS/issues/1324) | Accepted maturity scope and supported configuration, not a dependency on completing all architecture work |
| [#1053](https://github.com/seangalliher/ProbOS/issues/1053), [#1054](https://github.com/seangalliher/ProbOS/issues/1054), [#1056](https://github.com/seangalliher/ProbOS/issues/1056) | Installation, provider setup and doctor/quickstart |
| [AD-721c / #530](https://github.com/seangalliher/ProbOS/issues/530) | Bounded headset pilot, separate release claim and no reparenting |

No existing issues are reparented or closed by this program. Completed #965
workspace/workstation foundations, #873 stations, #1161 refresh repairs and #1309
AD-1259 telemetry consolidation stay completed. New regressions/residuals carry
their own measured reproductions, not a presumption that those changes never
shipped. Older issue-body absence claims require re-verification before building.

## Milestones and closure

### M0: Trustworthy working baseline and control exemplar

Repair independent High failures, add producer-asserting journey fixtures and
complete the first AD-1202 primitive/exemplar slices. Prioritize input -> agent
read, native identity eligibility, same-ID work state, message reconciliation,
notification navigation, focus and geometry. Visual design/prototyping may proceed
alongside those repairs; a reskin does not close them.

Use the existing supported configuration and isolate test data from the live ship.
Classify optional services honestly; do not enable every feature to satisfy a
misleading all-online headline. Receipt/progress/streaming work can proceed under
its existing owner as its real consumers become ready.

### M1: First successful collaboration

Deliver AD-1308's primary host and AD-1309's simple/fresh/resumed/progressive paths.
A new user identifies the crew and completes a simple task, then develops a
bounded two-agent objective with real inputs and clear scope. No manual window
arrangement or internal terminology is required. Preserve global navigation in
conversation and full views, and verify desktop/compact/mobile entry separately.

### M2: Shared work through verified outcome

Deliver the AD-1310 input/artifact handback slice and consume ready human-claim,
blackboard, goal-revision, verification and approval contracts. Require a real
artifact consumer, human revision/challenge, an explicit authorized blocker, and
resume after reconnect/restart. Show current disposition and dissent, not a
fictional unanimous agent team. Structured-content boundaries remain intact.

### M3: Cohesive, immersive desktop experience

Complete AD-1311 sessions, AD-1312 contextual management and AD-1313 visual/spatial
continuity against the same journeys. Calls have real media/teardown evidence;
workstations hand back the correct revision; the navigation/field/state grammar
is consistent across supported surfaces. Validate keyboard/screen reader, phone,
tablet, ordinary desktop, wide desktop, reduced motion and declared frame budgets.

Bank the HXI journey pack with AD-1186/#1123 rather than a new evaluator. Run an
initial bounded formative study with at least five representative new users:
simple query, collaborative input-to-artifact work, and blocker/resume. Proposed
exit target: at least four of five complete the simple task within five minutes
with at most one orientation hint, and complete the collaborative journey with
at most one navigation hint. Record every failure, abandonment, wrong turn and
assistance. This small study is usability evidence, not statistical proof of
general adoption or intelligence; declare targets before measuring them.

Program #1360 closes on the scoped desktop journeys and its release criteria:
all six architectural slices accepted, required existing contract slices integrated,
no unresolved Critical/High supported-journey defect, and all 24 findings traced.
Medium/Low residuals, including optional recreation, may remain separately open
only with explicit accepted scope, owner and scheduled follow-up; they cannot be
marked passed or silently removed from the coverage ledger. Remaining unrelated
work in existing parent programs does not become an HXI closure condition.

### M4: Independent immersive pilot

Existing AD-721c/#530 owns a one-workspace/two-crew WebXR pilot on one declared
headset/browser, reusing Three.js and the shared semantic host. Enter, orient,
identify collaborators, inspect/contribute to a shared object, inspect a governed
decision, and return to the same desktop work. Head/controller pose is transient
by default; gaze, proximity and ray hover never authorize work.

Require stationary/seated defaults, explicit recenter, no forced camera motion,
comfortable reach/text, captions, non-immersive alternatives, device-specific
frame measurements, sensor revocation and headset-loss recovery. Desktop and
emulator tests do not establish headset comfort, legibility or sensor privacy.
No hardware purchase, metaverse integration, multi-human spatial synchronization,
biometric profiling, or universal headset support is authorized by this plan.

M4 begins on ready shared contracts, not on completion of all fleet/Nooplex work.
It remains open until hardware acceptance is recorded. M3 does not claim VR
delivery, and the VR pilot does not delay independent desktop release.

## Implementation and compatibility gates

- Bound work to one issue or up to three tightly coupled issues. Reproduce on
  the current candidate; the live review's counts/timings are not fresh baselines.
- Every new public API/branch needs boundary tests. Every UI change needs Vitest;
  cross-surface contracts need real browser and production-consumer crossings.
- Assert the premise before an absence claim: new room identity, actual uploaded
  bytes, correct model/read path, event receipt, terminal record or media playback.
- Preserve canonical state, schema, protocol and public APIs, or ship tested
  compatible migration. Legacy data/layouts/links must reopen without data loss.
- Context-carrying generated UI is bounded declarative data, never instructions,
  script authority, arbitrary markup, or a substitute approval identity.
- Accessibility and resource lifetimes are acceptance criteria, not optional
  polish. Test stale replies, reconnect, cancellation and end-session behavior.
- Use the repository's focused tests, scoped adversarial review and canonical
  frozen-tree release gate. Changing source/test state invalidates broad evidence.
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

This document is a roadmap contract, not a set of ready-to-run implementation
prompts. Before each build, verify controlling APIs, constructors, current flags,
and consumers, then draft one bounded spec and its execution instructions per
repository policy. No live credentials, spending, production mutation, or relaxed
security controls are implicit in these issue allocations.

## Duplicate and allocation evidence

The authenticated GitHub account was the repository owner. The complete open
queue enumeration returned 70 issues with hasNextPage=false before filing. Two
successful canonical `scripts/ad_ceiling.py` runs reported:

| Source | Highest AD | Enumeration |
| --- | --- | --- |
| Git subjects, all refs | AD-1304 | 1,979 AD references |
| GitHub titles, all states | AD-1306 | 1,359 issues, 999 AD-titled; below 4,000 cap |
| In-flight prompt filenames | AD-1298 | 61 matching prompt files |

Prior ceiling: AD-1306, from GitHub. Allocated sequentially: AD-1307 through
AD-1313. GitHub issue numbers were returned in concurrent creation order and are
not assumed to equal AD order; the delivery register records each actual pair.

All-state repository-scoped searches were run for these concepts:

| Search | Returned candidates | Ownership use |
| --- | --- | --- |
| HXI spatial workspace Glass Bridge navigation responsive mobile VR experience onboarding | 6 | Completed #965/#873 and design/control lineage |
| HXI group chat duplicate replies attachments CSV room inputs native crew work identity unresolved live state | 12 | Completed context/projection/group foundations |
| HXI voice calls microphone avatar telemetry browser session close recreation game | 13 | Existing #1105; completed voice/avatar foundations |
| agentic_identity_unresolved crew summarizer child execution identity HXI work board stale status attachment fanout duplicate replies | 17 | Completed #834/#1047/#1051/#1301 versus new residuals |
| duplicate group replies transcript | 1 | #884 marker stripping is not duplicate rendering |
| CSV attachment group room inputs | 2 | #514/#549 uploaded-file foundations |
| browser session end close cleanup | 0 | Candidate search only; actual route enumeration established the observed missing end operation |
| recreation tic tac toe opponent turn | 1 | Completed #125 versus current opponent-turn failure |

Semantic searches identify candidates, not exhaustive proof of absence. Direct
reads verified the relevant active and completed owners, including #1142, #530,
#965, #1161, #1309, #1083, #1105, #1123, #1130, #1136, #1236, #1336, #1175 and
#1166. The #1166 comment records the already-accepted standing-rule-only decision;
the older body alone would have wrongly suggested it still needed that decision.

New publication: 19 issues total, comprising one program, six architectural
children and twelve focused repair/lifecycle children. Existing AD-1202 and
AD-721c were refined, not duplicated. No issue was closed, no code was shipped,
and no readiness status was changed by this planning exercise.
