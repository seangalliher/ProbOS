# HXI Live UX Review - 2026-09-07

Status: review complete for the explicitly listed coverage. This is an issue-ready
assessment, not a claim that every capability is enabled, production-ready, or
tested under every condition. No GitHub issues or new ADs were created by this
review.

## Executive recommendation

Keep the luminous mesh and its connections. Replace the inconsistent collection
of foreground windows with one coherent, contextual working surface. Before adding
visual polish, fix the workflows that currently undermine trust: duplicate replies,
attachments that do not reach the agent task, unexecutable work admission, stale
task status, and notifications that do not open the work they describe.

The live ship demonstrated useful capabilities: trace-grounded direct responses,
two-agent discussion, single and group call playback, notebook search/read, an
existing MCP connection, scratch editing/export, and embedded/streamed browsing.
The strongest obstacles are at the boundaries between those capabilities and the
human-facing workflow, not a lack of menus or features.

The 24 candidate identifiers below are local review IDs, not allocated AD numbers
or GitHub issues. Some are bug fixes; others are design decisions that should be
agreed before implementation. Search existing open and closed issues before filing,
and keep each reproduction independently actionable even when grouped in an epic.

## Objective and design constraints

Make everyday work intuitive, contextual, and pleasant without substantially
changing the luminous agent orbs or their visible connections. Concentrate the
redesign on navigation, forms, foreground work, state, and recovery.

Design references:

- [HXI Glass Bridge](../design/hxi-glass-bridge.md): preserve the mesh; make the
  current task central; keep controls accessible; surface decisions in context;
  make work visible rather than merely displaying a loading indicator.
- [Repository HXI principles](../../.github/copilot-instructions.md): human-first
  interaction, state-bearing motion, progressive disclosure, alert-driven layout,
  and agentic-first work with embedded workstations.

The older glass design contains both information-density and progressive-reveal
ideas. This review recommends contextual disclosure with stable navigation, not
turning every speculative visual treatment into a required feature.

Working hypothesis: the main usability deficit is how foreground surfaces compose
and communicate state, rather than the mesh visualization. The discriminating
check is to complete representative journeys through real entry points on desktop
and narrow viewports, checking context preservation, accessible controls,
completion evidence, and recovery.

## Scope and method

- Review the actual built HXI served by the running runtime, not a mocked SPA.
- Preserve the existing live data, configuration, approvals, and unrelated work.
- Use clearly labeled, bounded test conversations and synthetic task inputs.
- Calls and multi-agent collaboration are in scope for the extended review.
- Inspect consequential forms without submitting destructive actions, unrelated
  approvals, credential changes, installations, or external communications.
- Verify agent claims against live API records or tool traces where available.
- Do not infer absence of a capability from an undiscovered control.
- Report limitations explicitly, including audio hardware or unavailable services.
- Compile issue-ready findings; do not create GitHub issues or allocate new ADs
  during the review.

The first pass used a 1440 x 1000 desktop viewport and 390 x 844 narrow viewport.
The runtime was serving 80 agents, including 15 crew, when the extended review
started. These are observations at a point in time, not fixed product constants.

The live UI inventory was checked against the mounted surfaces in
[App](../../ui/src/App.tsx), the six-station
[registry](../../ui/src/components/bridge/stations.tsx), the 16-entry command
palette, the seven agent tabs, and the 14 settings sections. This is the boundary
of complete in this report: all principal exposed surfaces were accounted for,
not every endpoint, permission combination, or optional integration executed.

## Coverage ledger

| Surface or journey | Status | Evidence or next check |
| --- | --- | --- |
| Startup and component readiness | First pass complete | Runtime online; degraded integration reporting needs work |
| Mesh, avatar, and first-run introduction | First pass complete | Mesh and existing avatar rendered; preserve their visual identity |
| Direct conversation and self-query | First pass complete | One trace-backed self-query and one synthetic synthesis task |
| Direct-call lifecycle and audio controls | Exercised | Greeting, reply, real TTS playback, microphone capture, mute, end; physical audio quality not verified |
| New multi-agent collaboration | Exercised | New Ezri/Nova room, complementary replies, rename, duplicate-render check |
| Collaboration context and work/artifact handoff | Exercised with blockers | CSV stored but task not answered; native Start Work failed before model execution |
| Bridge Communications | Exercised | Expand versus Open Ward Room, channel loading, notification, navigation and administration |
| Bridge Personnel | Exercised | Complement, roster, roles, skill library, tool certifications, clinical, metrics |
| Bridge Science | Exercised with unavailable views | Notebook search/read and Records reader work; graph/timeline/backlinks/spatial return 503 |
| Bridge Operations | Exercised | Board, task detail, Quick Create, templates; no extra work submitted |
| Bridge Engineering | Exercised | System, catalog, MCP connection test/forms, disabled app gallery, scratch editor, browser |
| Bridge Command | Inspected | All 14 settings sections and search; Apply remained disabled/in sync |
| Agent Work, Memory, Profile, Service, Health, Self-image | Inspected | All seven tabs, controls, state, work history, voice settings, and diagnostics; no profile or permission edits |
| Global command surface and command palette | Exercised | Calculation, response, collapse/return, 16 palette destinations, keyboard launch |
| Scratch and embedded browser workstations | Exercised | Typed text exported byte-for-byte; public example page rendered |
| Browser Watch/Drive | Exercised | Allowed page opened, live stream rendered, scroll forwarded and visually confirmed; viewer closed |
| Browser external Bridge | Inspected only | CDP form viewed; live feature flag disabled; no personal browser connection |
| Single/group call lifecycle | Exercised | Both test calls ended, group marker persisted; physical voice quality not certified |
| Recreation | Partial, failed progression | Challenge and first move worked; no opponent move during bounded wait; forfeited and verified inactive |
| Duty bills | Inspected only | Four definitions and no instances; no ship-wide condition activated |
| Approvals and build decisions | Source/readiness inspection only | No pending capability requests; skill-request service unavailable; no approval manufactured or decided |
| Cloud pickers, connector authorizations | Settings/form inspection only | No account authorization, credential access, or external data mutation |
| Camera, screen sharing, live ambient sensing | Controls inspected only | Camera stayed off during calls; no private camera/screen capture initiated |
| Narrow viewport and keyboard navigation | Exercised | Desktop 1440 x 1000, phone 390 x 844, tablet 768 x 1024; tab order and field-label checks |

## Verified first-pass findings

### UX-01: Default conversation geometry obscures the primary workflow

Severity: High usability. Status: reproduced.

- On desktop, the empty artifact drawer occupied 360 of 418 available pixels,
  leaving a 58-pixel transcript. Collapsing it made the chat usable.
- At 390 x 844, the chat's Send and Close controls were outside the viewport.
- On a fresh narrow-viewport load, the Crew panel extended to x=500 while the
  viewport ended at x=390, clipping New chat.
- Opening a saved DM left the Crew list over the conversation; a normal avatar
  click was intercepted by the list's search input.

Recommendation: establish one responsive foreground workspace, collapse empty
secondary drawers, and make opening a detail view replace or dock its launcher.
The mesh remains visible around and beneath the work.

Acceptance direction: component tests plus real browser journeys must prove the
composer, Send, dismiss controls, and current content remain reachable at desktop
and narrow widths, with no pointer interception from inactive panels.

### UX-02: New chat does not communicate its context contract

Severity: High usability/context risk. Status: reproduced.

Selecting one crew member through New chat resumed a pre-existing DM thread. The
review messages were labeled but were not isolated in a fresh conversation. The
persisted thread ID and creation timestamp established that reuse.

Recommendation: distinguish Resume conversation from New conversation and explain
which prior context or memory remains available. Do not silently equate selecting
a person with creating a new thread.

Acceptance direction: new versus resumed thread identity, transcript boundaries,
and history sent to the agent must agree across UI, API, persistence, and reload.

### UX-03: Telemetry presents incompatible scopes and stale values

Severity: Medium. Status: reproduced; underlying count semantics not yet resolved.

- Ezri's self-query trace reported 17 episodes while the profile reported roughly
  190, without a visible scope distinction.
- A simultaneous comparison found the open Health tab showing 3 minutes uptime
  while the API reported 662.5 seconds, and 190 versus 196 episodes.
- The first-run introduction hardcoded 47 agents and directed the user to an input
  above, although the command control was below.

Recommendation: use shared definitions, show measurement time and scope, refresh
open views, and distinguish confidence from component readiness.

Acceptance direction: same-scope readings reconcile; different scopes have explicit
labels; values refresh without closing a panel; onboarding uses actual state.

### UX-04: Short conversation requests become opaque background work

Severity: Medium. Status: reproduced once; not a latency distribution.

A bounded, tool-free synthesis request returned a promotion notice after about
55 seconds and created a work item despite an explicit no-task request. The final
answer arrived about one second later. The task reached done and exactly one
report was persisted and shown, including after reload.

Recommendation: distinguish internal continuation from a user-delegated task,
respect response-only intent, and expose elapsed time, cancellation, and delivery
state without forcing the user to understand runtime promotion mechanics.

Acceptance direction: fast and slow responses, cancellation, reconnection, and
promotion deliver one attributable result with an honest visible state.

### UX-05: Operational degradation is disconnected from visible health

Severity: Medium. Status: reproduced.

The general health endpoint reported ok while the UI repeatedly received HTTP 503
with detail `skill request store not available`. Discord startup failed due to an
unavailable dependency. NATS initially warned but subsequently connected, so it
must not be described as currently offline based on its startup warning.

Recommendation: separate runtime liveness, integration readiness, and agent
confidence. Present actionable unavailable states and back off futile polling.

Acceptance: unavailable integrations cannot be mistaken for a fully operational
ship, repeated failed polling is bounded, and recovery updates both the feature
view and the readiness summary. See UX-16 for the related empty/error-state cases.

### UX-06: Conversation formatting and accessibility are inconsistent

Severity: Medium. Status: partially reproduced; extended accessibility review pending.

The chat rendered Markdown emphasis markers literally. The New chat overlay and
crew choices exposed generic elements rather than dialog/list semantics. Technical
agent identifiers appeared in self-query output instead of resolved callsigns.

Recommendation: render safe structured content, preserve copyable technical detail
behind human-readable names, and use consistent dialog, tab, list, focus, and
keyboard contracts.

Acceptance: safe Markdown lists, emphasis, code, links, long names, and error text
remain readable without overflow. Do not evaluate raw HTML from agents. Validate
actual accessible names and focus behavior rather than assuming generic elements
are unusable: the crew picker did support Arrow keys, Enter, and Escape in the
extended review. See UX-22 for the separate offscreen-focus defect.

## First-pass capability evidence

- Ezri's self-knowledge reply completed in about 32 seconds. The persisted trace
  contained one successful self_query call; trust 0.984 matched the live profile.
  She separated conflicting context from the tool measurement.
- The synthetic synthesis correctly distinguished delivery from effectiveness,
  identified uncertainty, and asked a relevant follow-up question. Its background
  task and delivered report were verified through live records.
- The mesh and existing Ezri avatar rendered. Rendering warnings alone did not
  establish a broken avatar.
- These observations do not establish broad safety, audio quality, multi-agent
  effectiveness, or complete feature readiness.

## Extended findings and recommendation plan

### UX-07: Call input/output modes need explicit, consistent controls

Severity: Medium, with privacy and accessibility implications.

Reproduction: open a crew DM, choose Call > Audio call, inspect the microphone and
speaker controls, click the microphone, and end the call.

Observed:

- Audio call created a persisted active meeting and kept the camera off. Ezri
  delivered a greeting. A typed in-call test received a reply and playback start
  in 11.2 seconds; the live TTS endpoint returned HTTP 200, and a 2.96-second audio
  element emitted playing and ended events without an error.
- Mute/unmute changed the output control correctly. End call removed the meeting
  flag and view; the microphone indicator was idle afterward. This does not prove
  every underlying capture track was released.
- The microphone button advertised a menu through aria-haspopup, but a normal
  click began capture. The mode menu is reached by right-click or Shift+F10.
- Capture produced an additional 54-character Captain turn and a reply. No
  controlled spoken phrase was supplied, so recognition accuracy and whether the
  input was ambient speech or transcription error remain unverified. The saved
  Captain message metadata did not distinguish typed from transcribed input.
- The view said 1 in meeting while showing the Captain and Ezri. The count is
  interpretable as crew count, not an explicit total participant count.
- A separate two-agent call produced correct short replies from Nova and Ezri.
  Two live TTS requests returned HTTP 200; 4.01-second and 3.83-second audio clips
  emitted playing and ended events sequentially. The entire request/playback check
  took about 36 seconds. Hang-up cleared meeting_active and persisted one
  Meeting ended marker naming both crew members. The rendered gallery remained
  cramped by the failed task's expanded contract, even after enlarging the window.

Recommendation: use a conventional call bar with independent, clearly labeled
microphone, speaker, camera, captions, device settings, and hang-up controls. Make
input mode and live capture unmistakable. Do not hide a consequential mode choice
behind right-click. Preserve input provenance and offer correction of a recognized
transcript before submission when using dictation mode.

Acceptance: test permission-denied, no-device, loading-model, listening,
transcribing, silent-input, error, mute, and hang-up states; prove microphone and
camera track teardown where promised. Include a controlled spoken round trip and
manual sound-quality check in addition to browser playback events.

Anchors: [CallMenu](../../ui/src/components/profile/CallMenu.tsx),
[ProfileChatTab](../../ui/src/components/profile/ProfileChatTab.tsx),
[GroupChatHeader](../../ui/src/components/profile/GroupChatHeader.tsx).

### UX-08: Avatar stability degrades during microphone and room transitions

Severity: High usability for calls; exact root cause not established.

Observed: the existing Ezri avatar initially rendered correctly. During microphone
capture, the browser log contained 312 avatar-telemetry connection warnings over
24.203 seconds, each reporting closure before connection establishment. After
switching from the DM to the group, the separate avatar window repeatedly appeared
  as a nearly uniform amber canvas instead of the character, including a dedicated screenshot.
Do not conflate the observed reconnect burst and blank rendering into one proven
root cause.

Recommendation: stabilize telemetry subscriptions across frequent microphone
updates and room changes; bind the visible avatar explicitly to its participant;
present a recoverable render-failure state. A group should not inherit a detached,
unexplained avatar window from a previous DM.

Acceptance: repeated DM/group/call/microphone transitions retain the correct
avatar, bounded subscription counts, nonblank rendered pixels, and functional
controls. Test with a real VRM asset and a failed asset load.

### UX-09: Group replies render twice despite single persisted delivery

Severity: High. Status: reproduced on two turns.

Reproduction: create a new Ezri/Nova room and send one request for both to reply.
Compare the visible transcript with the room's persisted messages.

Observed: the first turn had exactly one saved Captain message and two saved agent
messages, but each agent reply appeared twice in the UI, with different display
times. The next turn reproduced two visible occurrences per saved agent reply.
A subsequent room/session refresh showed the single persisted copies.

Recommendation: reconcile optimistic/progressive replies and event-delivered
messages by stable server identity; do not append a second independent copy from
the HTTP response. This is a rendering/delivery reconciliation finding, not proof
that the agents executed twice.

Acceptance: one visible row per persisted message across both response/event
orderings, reconnection, hydration, progressive reveal, and reload. Include a real
two-agent browser journey rather than only testing each delivery mechanism alone.

Anchors: [ProfileChatTab](../../ui/src/components/profile/ProfileChatTab.tsx),
[profileTranscript](../../ui/src/components/profile/profileTranscript.ts).

### UX-10: A successfully uploaded room attachment does not reach the user task

Severity: High. Status: end-to-end failure reproduced; routing versus tool-use
cause remains to be distinguished.

Reproduction: attach the deterministic synthetic shift CSV through the room's
chat composer, then ask both agents to identify task IDs from it.

Observed:

- Upload returned HTTP 200 and the persisted Captain message contained the CSV's
  content reference. A separate read retrieved all 306 bytes with the matching
  SHA-256 and discriminating rows T08 and T12.
- Both agents said they lacked the rows and declined the analysis after about
  58 seconds. Refusing to invent IDs was correct, but the requested work failed.
- The Files rail said No inputs yet despite the successfully attached message.
  After native Start Work, another Attach control appeared under Inputs.
- Final reconciliation after task binding and reopening found the same CSV in the
  room Inputs API with source=message, size=306, and filename=null. Thus this is
  not evidence of permanent input loss: the failed agent-read workflow, initially
  stale rail, and lost display name are separate observations. No second upload
  or invented file was needed to make the reference exist.

Recommendation: make conversation attachments and workspace inputs one coherent
user concept, with explicit agent-readable readiness and actionable failure. The
user should not need to discover two different attachment routes. Carry references
through the governed read path; do not solve this by inlining arbitrary large blobs.

Acceptance: upload -> room input visibility -> actual agent read -> correct
row-derived result -> persisted provenance -> reload. Include unsupported formats,
read failure, removed input, and cross-room isolation. The synthetic fixture has
unanswered reviews T04/T07/T08 and reworks T03/T08/T12, so a test must require those
IDs rather than merely repeat counts already present in the prompt.

Anchors: [ProfileChatTab](../../ui/src/components/profile/ProfileChatTab.tsx),
[WorkspaceFilesRail](../../ui/src/components/workspace/WorkspaceFilesRail.tsx),
[thread_fanout](../../src/probos/routers/thread_fanout.py).

### UX-11: Native Start Work admits an unexecutable child and gives poor recovery

Severity: High. Status: reproduced on one bounded task.

Reproduction: in the new room, open Files > Start Work. Request a short synthetic
handover briefing from inline facts with explicit success criteria and at most two
subtasks. No network, shell, repository edits, notebooks, or external communication
are needed.

Observed: admission returned created/discussing with one child after 12.4 seconds.
The child was assigned to a summarizer, not one of the room's two participants,
then failed before model use. The live traceback ended with
RuntimeError: agentic_identity_unresolved in _resolve_agentic_identity. The child
record contained execution_exception, zero tokens, no trace, and no artifact. The
parent reached failed; the room showed child_execution_failed and raw agent IDs.
Bridge gained a failure notification, but its initial wording only directed the
user back to the room for details.

Recommendation: check execution eligibility before admitting a child, preserve
identity/authority enforcement, and offer governed reassignment or a specific
recoverable blocker. Explain who will do the work and why, including helpers outside
the room. Translate technical failures into an understandable cause, next action,
and expandable diagnostics. Never label this task complete or verified.

Acceptance: a normal synthetic Start Work request reaches a usable verified
deliverable. An unresolved identity becomes an explicit recoverable state without
bypassing the check, duplicate dispatch, or an unexplained terminal failure. The
same task identity must connect room status, Bridge attention, execution evidence,
and result. Assert artifact delivery, not only child state transitions.

Anchors: [WorkspaceFilesRail](../../ui/src/components/workspace/WorkspaceFilesRail.tsx),
[CrewCollaborationPanel](../../ui/src/components/crew/CrewCollaborationPanel.tsx),
[crew_executor](../../src/probos/cognitive/crew_executor.py),
[agentic_dispatch](../../src/probos/cognitive/agentic_dispatch.py).

### UX-12: Work setup and progress consume the conversation instead of supporting it

Severity: Medium; combines with UX-01 to become blocking in compact windows.

Observed: Start Work was inside the Files rail. Its three separate textareas asked
for overlapping upfront specifications; Retry blocked work appeared on a new
request. The created session repeated the entire goal, criteria, deliverable,
internal owner IDs, and Duplicate resumes counter above the chat. With Files open,
the remaining transcript measured 118 pixels wide and 16 pixels high.

Recommendation: place the primary work action in the room header. Start with a
plain-language objective, derive an editable brief, and reveal advanced criteria
when relevant. Once admitted, show a compact progress summary with a useful next
action; expand the full contract and diagnostics on demand. Show retry only for a
state that actually supports it.

Acceptance: current conversation and composer remain usable during setup,
execution, failure, and result review. The room's primary action and failure
recovery can be found without opening a file-management drawer.

### UX-13: Bridge launch paths disagree and navigation layers overlap

Severity: High where it prevents reaching or leaving work; otherwise Medium.

Reproduction and evidence:

- Communications > Expand opened Ward Room by setting its view state, but left it
  with no channel list. Communications > Ward Room then loaded channels and
  populated threads. The expand action did not call the same initialization path.
- Opening the full Work Board left Bridge above its Quick Create and template
  controls; normal pointer clicks were intercepted until Bridge was dismissed.
- The global Crew button covered the Canvas return button on the full Work Board.
  Keyboard focus plus Enter could activate Canvas; pointer activation failed.
- The top BRIDGE toggle intercepted a click aimed at Bridge's own close button.
- Crew, Personnel, Notebooks, Records, and workstation actions open different
  panel forms, dimensions, and depth behavior while leaving previous panels around.

Recommendation: route each destination through one public opening action, including
data initialization. Introduce one consistent workspace and panel lifecycle, shared
close/back/focus behavior, and reserved positions for global controls. An expand
action should describe its actual destination. Preserve departmental grouping as
optional navigation, not as a prerequisite for finding everyday work.

Acceptance: each launch path reaches the same ready destination; full-workspace
navigation and return are pointer- and keyboard-accessible with Bridge open or
closed. Exercise real transitions, not isolated component rendering.

Anchors: [stations](../../ui/src/components/bridge/stations.tsx),
[BridgePanel](../../ui/src/components/BridgePanel.tsx),
[App](../../ui/src/App.tsx),
[WardRoomPanel](../../ui/src/components/wardroom/WardRoomPanel.tsx).

### UX-14: A failure notification acknowledges instead of opening its context

Severity: High for recovery discoverability.

Observed: the test session failure raised a Bridge badge and the message Crew
session failed / Open the existing crew room for details. Clicking the notification
acknowledged it, cleared the unread badge, and did not open the room within the
10-second observation window. The inspected notification component's default card
click calls the acknowledgement endpoint; the test card had no separate Open room
action.

Recommendation: the primary action should open the exact room/task at its blocker
or result, with acknowledgement secondary or an explicit consequence of viewing.
Keep unresolved work discoverable after acknowledgement. Distinguish a notification
from an approval or a decision requiring action.

Acceptance: failure event -> badge -> actionable notification -> correct room and
task -> diagnostic/recovery control. Reading or acknowledging does not imply the
underlying failure is resolved. Include keyboard activation and stale-target cases.

Anchor: [BridgeNotifications](../../ui/src/components/bridge/BridgeNotifications.tsx).

### UX-15: Work Board and Bridge counters disagree with live task state

Severity: High. Status: reproduced.

Observed: the native test child was failed in the live work-item API, with
crew_execution.status=failed and stopped_reason=execution_exception. The Work Board
placed it in Backlog and its opened detail called it open. Bridge's Operations
summary displayed Q/W/R/D all zero, while the full board showed backlog and many
completed items. Different populations may explain some counters, but the UI does
not name those populations. The same test child identity specifically proved the
board/API failure-state mismatch.

Recommendation: project one canonical lifecycle and refresh/event contract into
every work surface. Distinguish intentional tasks from background conversational
continuations; make Needs attention the default actionable slice. Use human labels
instead of Q/W/R/D, raw state tokens, and prompt-length task titles.

Acceptance: create, dispatch, fail, block, resume, complete, and reload preserve
state across API, room, board, detail, and Bridge. Tests must compare one known
identity through every consumer and explain filtered counts rather than comparing
unrelated totals.

Anchors: [WorkBoard](../../ui/src/components/work/WorkBoard.tsx),
[BridgeKanban](../../ui/src/components/bridge/BridgeKanban.tsx).

### UX-16: Disabled services are presented as empty information

Severity: Medium, rising to High when used as evidence for a decision.

Observed:

- Records List and Reader worked, but graph, timeline, and backlinks returned HTTP
  503. Graph said No graph data; Timeline said No timeline data. Direct readback
  returned Knowledge Browser not available. A user could infer absence of history
  or relationships when the query capability was unavailable.
- Spatial layout returned HTTP 503 while the view suggested enabling configuration.
- MCP Apps explicitly said MCP App Host disabled, a useful honest-state precedent.
- System Management reported 12/12 services online while the skill-request store
  and optional knowledge views were unavailable. These may be different service
  scopes, but the headline does not state the distinction.

Recommendation: standardize loading, empty, disabled, unauthorized, degraded, and
failed states. Each unavailable view should identify the prerequisite, an allowed
next action, and whether the rest of the workspace remains usable. Do not replace
errors with empty collections or zero-valued metrics.

Acceptance: intentional feature-off, service failure, true-empty, and populated
responses produce different accessible states, with no transient empty claim while
loading. Configure or request access without bypassing existing policy.

### UX-17: Navigation reflects implementation taxonomy instead of user goals

Severity: Medium. Design recommendation grounded in the exercised routes.

Observed: top-level Crew opens conversations, while Bridge > Personnel > Crew
opens Ship's Complement, and Personnel opens Ship's Office. Science offers both
Notebooks and Records, which share document content but use different search and
reader experiences. Communications combines thread activity, two permission
settings, history search, and 123 DM channels, including many with zero messages.
Browser also has a Bridge mode with a different meaning from the main Bridge.

Recommendation: make everyday destinations People, Conversations, Work, Knowledge,
and Settings discoverable in one stable navigation/command palette. Preserve the
ship names and department colors as secondary context. Bridge should lead with
Needs you, In progress, and Recent results, with administration behind explicit
settings. Do not replace the mesh with a generic dashboard or app-launcher grid.

Acceptance: representative users can find a named crew member, start/resume a room,
locate an output, inspect a blocker, and change a relevant preference without
knowing the repository's subsystem names. Measure completion and wrong turns.

### UX-18: Capability, qualification, and research views need honest semantics

Severity: Medium.

Observed: Skill Library displayed 53 skills, 16 crew, and 53 gaps; Roles had no
templates. Ezri's record separately showed zero developmental/cognitive skills and
four available runtime skills. Ship's Locker listed 42 tools, four skills, and 84
mesh capabilities, largely labeled no explicit grants, with no search input or
filter controls in the enumerated live panel. Effective inherited access is a
different concept and has its own MCP Agent toolbox view. Behavioral Metrics used
Crew intelligence - observed and Quality 0% without an immediate sample-size or
validity explanation, plus an internal future-AD message.

Recommendation: explicitly separate available capability, effective permission,
formal qualification, evidence of proficiency, and unmeasured research signals.
Use searchable, task-oriented capability summaries with provenance and human
callsigns. Show Unknown/not measured where evidence is absent; do not imply that
no explicit grant means incapable or that an ungrounded zero means poor quality.

Acceptance: a working inherited capability is not presented as unavailable; no
qualification is not confused with no capability; metrics disclose denominator,
window, freshness, and interpretation limits. Existing task success does not by
itself prove the qualification record is wrong.

### UX-19: Settings and administration need contextual entry and safer separation

Severity: Medium, with authority-changing controls requiring focused review.

Observed: Settings offers 14 sections, search, Apply/Discard, and an in-sync state;
the review visited all sections without changing values. Several numeric fields
had no associated HTML label or accessible name despite visible descriptive text.
Searching domain returned no matches even after the browser reported a domain
allowlist refusal. Tools copy still described adding MCP servers as future work
although the live MCP Servers form provides that capability. Personnel puts profile
inspection and many immediate permission switches in the same long record. The
global shutdown action remains at Bridge's footer during everyday work.

Recommendation: retain explicit draft/apply/discard where appropriate, add field
labels, field-level help and validation, and link denials directly to the relevant
policy or governed request. Separate crew inspection from grant/restrict editing.
Use an explicit administration area for destructive/session-ending controls, with
clear consequence and confirmation. Remove stale roadmap text from the product.

Acceptance: all fields are named and keyboard-operable; unsaved changes are clear;
policy changes show affected scope and inherited effects; cancellation leaves
state untouched; denying an action never silently enables it.

### UX-20: Workstations work in isolation but lack a clear task handoff

Severity: Medium; small export naming inconsistency is Low.

Observed: the scratch editor accepted synthetic Markdown and exported all 114 bytes
correctly. It suggested Scratch.txt despite a Markdown language label. Its visible
actions were Copy and Download, without a task/room save or agent-handoff action.
Embedded browser rendered Example Domain successfully. Watch mode refused the same
destination under the configured domain allowlist and displayed that reason.
The external-browser Bridge mode asks for a CDP endpoint; it was inspected but not
connected to a personal browser. The existing Microsoft Learn MCP connection test
passed and advertised three tools; no registration or credentials were changed.

An allowed Watch destination, the public PyPI pytest page, subsequently opened
successfully. Its live 1280 x 720 stream rendered. Drive forwarded a 640-pixel
scroll through the session input endpoint, which returned forwarded=true, and the
stream visibly moved to the lower page content. This establishes a working
Watch/Drive path without weakening the domain policy. The external-browser Bridge
feature was configured off; its connection path was not exercised.

Recommendation: keep lightweight workstations, but bind title, owner, current task,
save destination, and Hand back to crew explicitly. Explain browser mode differences
through what the user can do and who controls the session. Offer governed access
requests for blocked destinations, not an invitation to weaken the allowlist.

Acceptance: edit -> save/export -> reopen or hand off -> agent consumes the correct
version. For browser modes, test allowed, denied, embed-blocked, disconnected, and
handoff states without cross-session leakage. Suggested extensions match the chosen
document format. Do not build a separate desktop suite as part of this improvement.

### UX-21: Global command results expose redundant agents as duplicate answers

Severity: Medium. Status: reproduced with a deterministic arithmetic request.

Reproduction: ask the global command surface to calculate 17 multiplied by 23 and
return only the answer. The request took about 28 seconds and the API returned
391 followed by 391. Its evidence contained two successful calculator-agent results
for the same intent. The visible conversation also displayed 391 twice.

Unlike UX-09, this duplication is already present in the server response. It is
not proof of an accidental duplicate UI append or duplicate HTTP submission.

Recommendation: present one coherent answer when equivalent redundant results
agree, retaining the separate contributors and evidence behind the answer. Preserve
genuine disagreements and distinct outputs. Investigate first-answer latency with
trace timings; one 28-second sample is not a latency distribution.

Acceptance: equivalent fan-out results produce one answer, disagreements remain
visible, and contributor/evidence records are not discarded. Test through the
global command API and its renderer, not only the calculator implementations.

Anchor: [IntentSurface](../../ui/src/components/IntentSurface.tsx).

### UX-22: Closed panels remain in keyboard navigation; form labels are incomplete

Severity: High accessibility/usability.

Reproduction: close Bridge and Ward Room, focus the visible Crew button, then use
Tab. In the measured sequence, 12 of 14 steps landed outside the viewport, including
Bridge controls at x=1449 or greater and a Ward Room container at x=-420. The
closed panels were translated away but remained focusable.

Additional form evidence: the mobile/tablet LLM settings fields had visible text
descriptions but no associated HTML label, aria-label, or aria-labelledby. Settings
filled the viewport, but its 280-pixel sidebar plus fixed field grid pushed text
inputs to x=560 through x=880 at both 390- and 768-pixel viewport widths.

Working precedents: the crew picker supported ArrowDown, Enter, and Escape; the
command palette exposed listbox/option semantics and launched Notebooks by keyboard;
Bridge station headers and clinical crew selectors were semantic controls. Those
behaviors should be preserved and extended, not replaced indiscriminately.

Recommendation: make inactive surfaces inert/hidden to focus and accessibility,
restore focus to the opener, associate every field with its label, and use one
responsive form primitive. Provide keyboard alternatives for dragging/resizing.
Do not treat missing ARIA as proof of missing keyboard support, or a successful
keyboard path as proof that screen-reader semantics are complete.

Acceptance: no Tab stop in a closed/offscreen surface; all active fields have a
meaningful accessible name; modal focus is contained and restored; touch and
keyboard users can reach every primary action at 390, 768, and 1440 pixels. Test
with a screen reader as well as DOM assertions. See UX-01 for conversation geometry.

### UX-23: Recreation accepts a move but does not provide a bounded opponent turn

Severity: Medium for this optional workflow. Root cause not established.

Observed: Challenge to Tic-Tac-Toe opened a game against Ezri. The Captain's center
move was accepted and persisted. Both the UI and live game record remained on
Ezri's turn with one move on the board, including an additional explicit 60-second
wait. No opponent move was observed. The review then used Forfeit; the server
returned forfeited and the active-game endpoint returned null.

Recommendation: expose opponent readiness and elapsed response state, provide a
bounded failure/retry path, and verify that the agent actually receives and acts on
its turn. Present board positions with accessible row/column names rather than
only implementation indexes 0-8. Keep recreation optional and distinct from work.

Acceptance: challenge -> valid Captain move -> opponent move -> terminal outcome
works end to end, including a slow/unavailable opponent and deliberate forfeit.
Record a completed game, not only successful game creation. Never turn missing
response evidence into a fabricated opponent move.

Anchors: [GamePanel](../../ui/src/components/GamePanel.tsx),
[useStore game actions](../../ui/src/store/useStore.ts).

### UX-24: Browser sessions lack an explicit user-visible end lifecycle

Severity: Medium; privacy and resource-lifetime implications.

Observed: Watch opened a new Captain-owned browser session and Drive worked. The
enumerated visible controls offered Refresh, Drive, Open, a session selector, and
Close Browser Workstation, but no End session. The live OpenAPI enumeration of
all browser paths exposed session list/create, stream, input, bridge connect,
recordings, and action acknowledgement/abort; it did not expose session close.
The DELETE route concerned recordings, not the active session.

Drive was turned off and the viewer closed; the stream element unmounted, but the
session remained in the live session list. Configuration set a maximum duration of
1800 seconds and a 60-second reaper interval. Expiry was not awaited or verified;
closing the viewer must not be described as closing the browser.

Recommendation: distinguish Stop watching, Release control, Hand to crew, and End
session. Show owner, sharing scope, recording state, and expiry. Add a scoped public
end-session operation and safe confirmation for sessions holding work, without
closing unrelated browsers or deleting recordings implicitly.

Acceptance: ending a selected session tears down its page, input, and streams,
updates every viewer, and leaves other sessions/recordings intact. Closing just the
viewer preserves the session only when that behavior is explicit. Test expiry and
reconnection separately from a user-requested end.

Anchors: [BrowserWorkstationPanel](../../ui/src/components/workstation/BrowserWorkstationPanel.tsx),
[browser_stream routes](../../src/probos/routers/browser_stream.py).

## Proposed interaction model

### Preserve the mesh; reorganize the working surface

Keep the orb forms, department clusters, breathing, trust/activity colors, visible
connections, and direct agent selection. Do not substitute a dashboard, flat roster,
marketing page, or grid of application cards for the mesh. Its recognizable visual
identity is a strength and an explicit user constraint.

Make only supporting adjustments: limit bloom behind reading surfaces, maintain
legible selected-agent labels, offer optional focus on the current participants,
and respect reduced motion. The active task may soften the background locally;
closing it should return to the same mesh context rather than reset the camera.

The original Glass Bridge's desktop/laptop/tablet/mobile adaptations, task-centered
foreground, and decisions-rise principle are directly relevant. Its speculative
gaze-based scheduling, decorative treatments, and dense telemetry are not a mandate
for this repair. Current user preference takes precedence over speculative details
in the older document.

### One navigation model

Provide a stable compact navigation and searchable command palette. Keep it
reachable during global chat, agent chat, work, calls, and full-screen views.

| Human goal | Primary destination | Context retained |
| --- | --- | --- |
| Find or contact a crew member | People | Callsign, role, availability, current work |
| Resume or start a conversation | Conversations | Participants, history boundary, purpose |
| Delegate or inspect work | Work | Objective, owner, status, evidence, next action |
| Find a document or learned result | Knowledge | Source, author, scope, provenance, search |
| See what needs attention | Bridge | Unresolved decisions, blockers, active work, recent results |
| Change preferences or administration | Settings | Selected person/task/service and affected scope |

Department names and the ship vocabulary remain useful secondary context. They
should not force a new user to know that a browser is under Engineering or that
Crew means conversations in one place and a roster in another. Retain the existing
palette implementation and improve its discoverability rather than building a
second competing launcher.

### One foreground workspace, contextual detail

- Opening a destination replaces or docks its launcher, instead of stacking a new
  window across the controls that launched it. Keep a clear Back/Close path.
- Default to one primary workspace and at most one secondary detail sheet.
  Optional pinning/comparison can support expert users, but manual window placement
  should not be necessary for the first successful task.
- Use responsive minimum dimensions and a single-column mobile layout. On phones,
  person lists and details are separate views; Files is a sheet, not a permanent
  column. On tablets, collapse the settings sidebar before sacrificing the fields.
- Remember context and drafts when moving between views; do not imply a new
  conversation when the existing history is reused.

### Conversation and room anatomy

The header should lead with the person/room name, current purpose, participants,
and call state. Offer Call and Start work there. Use plain language for internal
identifiers, keeping full IDs available in diagnostics or copy actions.

Keep the composer usable at all times. It should clearly identify its recipient:
Ship's Computer, a named crew member, or a named room. Text, file, and voice inputs
should share one visible context contract. An attachment should show uploading,
ready for the crew, unavailable, or removed; successful upload alone is not proof
the next agent can read it.

Use Chat, Work, and Files as related views or context-aware sections of one room,
not separate products. Display a compact task status above the conversation and
expand the full goal/criteria/evidence only when requested. During a call, foreground
the participants, current speaker, captions, and call controls; do not let an old
failed task consume most of the gallery.

### Work and decisions

Start with a plain-language objective. Offer an editable proposed brief containing
success criteria, intended deliverable, constraints, participants, and authority.
Reuse the existing governance and crew workflow rather than inserting a central
cognitive dispatcher. Advanced templates and explicit criteria remain available
when the task warrants them.

Show honest milestones: preparing, agent working, waiting for input, blocked,
verifying, and delivered. A message count is not collaboration effectiveness; a
producer event is not completed delivery. A completed task must identify its result
and the evidence supporting completion. A failed task must identify a cause and a
permitted next action. Acknowledged is never a synonym for resolved.

Bridge should open on Needs you, then Active work, then Recent results. Service
readiness belongs in a separate inspectable area. A failure or approval opens its
exact room/task in context. Do not put permission administration or shutdown among
the normal conversation actions.

### Forms, typography, and state

Use one field family with visible labels, accessible names, units, defaults,
validation, and a deliberate save model. Use searchable selectors instead of long
unfiltered lists or comma-separated fields where structured controls fit. Separate
read-only profile information from grant/restrict, personal voice settings, and
clinical administration.

Use the existing visual language, with geometric sans text for conversation and
forms and monospace for identifiers/metrics. Make text readable at ordinary zoom;
do not solve overflow by shrinking essential text. Preserve functional color and
state-bearing motion, but do not make color the only signal. Standardize empty,
loading, disabled, denied, failed, and stale states across all surfaces.

Keep optional technical diagnostics such as Duplicate resumes, DSL signals,
internal skill IDs, and research metrics available, but not in the default working
hierarchy. A familiar action should not require knowledge of an AD number, CDP,
PQS, or a runtime error code.

## Issue candidates and repair order

Repair ordering is not an AD allocation or permission to implement every change
as one large rewrite. The rows below preserve separate acceptance boundaries.

| Candidate | Priority | Kind | Recommended batch |
| --- | --- | --- | --- |
| UX-01 Conversation and mobile geometry | High | Bug + layout contract | 1: usable and truthful core |
| UX-09 Group duplicate rendering | High | Delivery reconciliation bug | 1 |
| UX-10 Attachment-to-agent handoff | High | End-to-end capability failure | 1 |
| UX-11 Unexecutable Start Work child | High | Admission/execution contract | 1 |
| UX-15 Stale work status across consumers | High | State projection bug | 1 |
| UX-14 Notification-to-work navigation | High | Recovery workflow | 1 |
| UX-08 Avatar transition stability | High | Media lifecycle investigation | 1, call slice |
| UX-22 Hidden focus and form accessibility | High | Accessibility contract | 1, shared UI slice |
| UX-02 New versus resumed context | High | Product contract + UI/API | 2: coherent interaction |
| UX-13 Consistent launch and return paths | High/Medium | Navigation lifecycle | 2 |
| UX-17 Goal-oriented navigation | Medium | Design decision | 2 |
| UX-12 Contextual work setup/status | Medium | Form and room redesign | 2 |
| UX-07 Explicit call modes | Medium | Call UX + capture lifecycle | 2 |
| UX-06 Safe formatting and human labels | Medium | Shared presentation | 2 |
| UX-19 Contextual administration | Medium | Settings/authority UI | 2 |
| UX-03 Scoped, fresh telemetry | Medium | Data contract + presentation | 1/2, with status work |
| UX-05 Integration readiness | Medium | Operational state | 1/2, with availability |
| UX-16 Disabled versus empty | Medium | Shared state contract | 1/2, with availability |
| UX-04 Slow-turn continuation | Medium | Conversation lifecycle | 2/3 |
| UX-21 Coherent global answers | Medium | Result aggregation | 3: capability polish |
| UX-18 Capability/evidence semantics | Medium | Information design | 3 |
| UX-20 Workstation handoff/export | Medium/Low | Workflow completion | 3 |
| UX-24 Browser session end lifecycle | Medium | Resource/privacy lifecycle | 3, browser slice |
| UX-23 Recreation opponent turn | Medium | Optional capability failure | 3 |

Start with a bounded vertical slice: open a new two-person room, attach the
synthetic CSV, obtain one grounded contribution per agent, start bounded work,
receive the result, and reopen it from Bridge. Passing that journey would repair
more of the lived experience than independently restyling every panel.

Then prototype the navigation/workspace contract with representative users before
moving all forms. Preserve old routes or tested compatibility during migration;
change one family of surfaces at a time. Do not couple the redesign to new agents,
new storage, a new renderer, or replacement of the orb mesh.

## Verification contract for follow-up work

- Add component tests for every changed UI behavior and browser journeys for
  cross-component workflows, in accordance with repository instructions.
- Use real producer/consumer contracts for message identity, attachment references,
  task state, result evidence, and media lifecycle. Mocking each side separately is
  insufficient for the failures observed here.
- Assert fixture premises: a genuinely new room, a real retrievable attachment,
  discriminating CSV rows, known task identity, actual pending request, or decoded
  media. No result is not evidence if the setup never reached the consumer.
- Test 390 x 844, 768 x 1024, and 1440 x 1000; include a fresh narrow load, resize
  of an open view, long text, multiple participants, validation errors, and drawers.
- Require pointer, keyboard, and screen-reader access to primary actions; no
  offscreen tab stops or hidden elements intercepting input.
- Verify reconnect, refresh, late response, cancellation, and retry. One delivered
  message/result must remain one after hydration, not merely before reload.
- Test actual voice start/end and stream pixels across state changes. Hardware
  listening quality, microphone accuracy, camera preview, and screen-share consent
  still require controlled human/device acceptance testing.
- Keep governance, authorization, privacy, consensus, and audit intact. A blocked
  capability should offer a governed route, not a silent bypass or a dead end.

Suggested usability measures, not measured results from this review: task success,
time to first useful answer, time to recover a blocker, wrong-navigation turns,
manual resizing needed, duplicate messages, and whether a user can explain who is
working on what. Research metrics are not substitutes for those outcomes.

## Evidence and test footprint

Local screenshots are retained under logs and are not staged for publication.
Attach selected, privacy-reviewed images to filed issues; do not assume ignored
local evidence links will exist in a public checkout.

| Observation | Local evidence |
| --- | --- |
| Default chat compressed by empty artifacts | [Desktop chat](../../logs/probos-live-20260907-02-chat-default.png) |
| Phone chat clipped | [Mobile chat](../../logs/probos-live-20260907-05-mobile-chat.png) |
| Single audio call | [Call view](../../logs/probos-live-20260907-08-audio-call-start.png) |
| Room attachment and repeated replies | [Group conversation](../../logs/probos-live-20260907-10-group-with-attachment.png) |
| Files rail initially empty | [Files rail](../../logs/probos-live-20260907-12-room-files-empty.png) |
| Start Work form geometry | [Work form](../../logs/probos-live-20260907-13-start-work-form.png) |
| Avatar after room transition | [Avatar rendering failure](../../logs/probos-live-20260907-14-group-avatar-after-switch.png) |
| Bridge and overlapping surfaces | [Communications](../../logs/probos-live-20260907-15-communications-expanded.png) |
| Group call dominated by failed work contract | [Group call](../../logs/probos-live-20260907-18-group-call.png) |
| Duplicate global answer | [Calculation result](../../logs/probos-live-20260907-19-global-calculation.png) |
| Recreation first state | [Game](../../logs/probos-live-20260907-20-recreation-start.png) |
| Phone settings overflow | [Settings fields](../../logs/probos-live-20260907-23-settings-mobile-fields.png) |
| Live browser stream before/after Drive | [Watch](../../logs/probos-live-20260907-24-browser-watch.png), [scrolled](../../logs/probos-live-20260907-25-browser-drive-scrolled.png) |

The synthetic CSV and byte-verified scratch export are local review artifacts,
not production source changes. The report records enough discriminating values
to reconstruct them without retaining personal data in a regression fixture.

Live state intentionally left for traceability:

- The pre-existing Hello Ezri DM contains labeled direct/call test turns. The
  earlier New chat action reused that thread; this was disclosed, not concealed.
- One new room, HXI UX Review - Synthetic Handover, contains the two-agent tests,
  the synthetic input reference, one failed native work session, and a completed
  group-call end marker. The failed task is evidence, not unfinished execution.
- The test game was forfeited and verified absent from active games. Both calls
  were ended and their meeting flags checked inactive.
- The Captain-owned public-PyPI browser session remained managed after Drive was
  disabled and the viewer closed. Configured expiry is 30 minutes, with a 60-second
  reaper; actual expiry was not verified. No unrelated browser process was killed.
- No approval was granted, no ship-wide bill activated, no camera/screen content
  deliberately captured, no credential changed, and no integration installed.
  One microphone capture did produce an unplanned input turn; its source and
  recognition accuracy were not inferred from the text.
- No runtime or UI source was changed. Existing model configuration and planning
  edits were preserved. The runtime remains running for the user.

## Residual coverage limits

This review does not certify arbitrary collaborative tasks, safe destructive
execution, external connector actions, authentication flows, federation, desktop
integration, or successful native-work artifact delivery. The attempted native
session failed before that delivery stage, so an end-to-end result/approval/retry
journey remains an acceptance requirement, not an implied pass.

No pending capability request was available in the live queue, and the skill
request store was unavailable. Approval dialog behavior was inspected in source,
not exercised by inventing a production request. Camera/screen consent, controlled
speech recognition, physical audio quality, and a complete recreation game need
separate device-backed testing. Disabled Knowledge Browser graph/timeline, Spatial
Explorer, MCP Apps, and external-browser Bridge were not enabled for this review.

The complete finding set is therefore actionable but bounded: it names what
worked, what failed, what merely needs better design, and what remains unverified.

## Roadmap follow-through

The Captain's subsequent spatial-collaboration request is planned under
[AD-1307 / #1360](https://github.com/seangalliher/ProbOS/issues/1360) and the
[HXI Spatial Collaboration Program](hxi-spatial-collaboration-program.md).
That program supplies one primary issue owner for each UX-01 through UX-24,
six architectural implementation slices, shared-owner dependencies, and separate
desktop and VR acceptance. Existing AD-1202 control primitives and AD-721c VR
ownership are refined, not duplicated. This linkage does not change the measured
review evidence, mark a finding repaired, or claim that any new UX has shipped.
