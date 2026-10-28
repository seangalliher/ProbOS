# Draft: AD-1289 (#1336) amendment from Agensh

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

This file is a staging draft and is not posted. It has two parts:

- **Part A**, the text to append to the body of #1336. It follows the structure of the 2026-10-11 MASS amendment and the 2026-10-25 CORAL amendment on #1337.
- **Part B**, which stays here. It records the decision the Captain must take, the dependent issues and the grep evidence.

---

## Part A — text to append to #1336

## Amendment (2026-10-28): work-item ownership, failed attempts and scope overlap, from Agensh

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28. Applied on the Captain's approval, YYYY-MM-DD.

**Prior art:**
- Agensh (Zhan et al., Microsoft Research, arXiv 2609.26781; [microsoft/Agensh](https://github.com/microsoft/Agensh)). Absorption note: `docs/research/agensh-organization-harness-absorption.md`.
- Agensh workers share an append-only board of short typed entries. The kinds are `OBSERVED`, `FACT`, `FAIL` ("a hypothesis you falsified ... it stops peers spending budget on it"), `CLAIM` and `PATCH_SUMMARY`.
- Workers claim an area before working on it, and settle any overlap between claims by direct message.
- A new board entry or direct message is added to the result of the worker's next infrastructure tool call, so it arrives mid-turn.

**Evidence caveat:**
- The paper varies only the number of agents. **No mechanism is ablated**, so nothing shows that `FAIL` entries, claims or mid-turn delivery help on their own.
- Compute is not normalized: every configuration gets the same 6-hour wall clock, with one model session per worker.
- No run count or variance is reported, and several curves are not monotonic.
- The single-agent baseline is kept running by a stop hook, while the teams have a 10-minute idle nudge.
- It uses one model (GPT-5.6-sol) and five ProgramBench tasks, and runs 1,024 agents only on pandoc.

This amendment therefore uses **none of the paper's numbers**. Everything it adds ships **default off**, and it carries its own measured acceptance.

**The gaps:**
- **Ownership.** As written, this issue ties the board to the CrewSession/elastic team instance, so ordinary crew work cannot have a board. Elastic teams stay inert until AD-1288 (#1335): `ElasticCommissionService` is staged under AD-1288 in the AD-1270 dormant-class baseline. A CrewSession is itself a parent work item (`work_type == "crew_session"`, `src/probos/cognitive/crew_session.py:2542-2544`), and its session id is that item's id (`crew_session.py:6130`).
- **Failed attempts.** No entry kind records an author's own disproved approach. `challenge` and `dissent` both target another entry.
- **Overlap.** Work-board claims are exact-item claims. The pull claim is in `src/probos/routers/workforce.py:388-402` and `src/probos/tools/work_item_pull_tool.py`. A request is deduplicated only by exact normalised title (`src/probos/agent_work.py:123-130`, `:347-348`). Nothing tells two holders that their work overlaps.
- **Delivery.**
  - Agent-work notices are terminal only: `NOTICE_TERMINAL` is the only notice kind (`agent_work.py:56`). They are posted to the Ward Room (`src/probos/agent_work_runner.py:393-414`, `:595-615`), and their table exists only when `agent_work` is enabled (`src/probos/workforce.py:1686-1702`; the default is off, `src/probos/config.py:3580`).
  - Nothing reaches an agent during its turn except the loop's own per-request blocks: the budget note, the AD-1322 economic block and the AD-1324 tier block (`src/probos/cognitive/swe_harness/agentic_loop.py:1749-1776`).

### Added decision

- **The owner is a work item, and a CrewSession is one kind of owner.** A board is keyed by `owner_work_item_id`, which must be a root work item.
  - **CrewSession.** The owner is the `crew_session` parent. Its id equals the session id, so nothing in this issue's CrewSession design changes: entries still carry task, slot and attempt linkage. AD-1288 and AD-1290 read the same board under the same id.
  - **Any other root work item.** A board opens on the first accepted append by a member. An item nobody writes to has no board.
  - **Where a descendant writes.**
    - Plan children write to their root's board through `parent_id`.
    - Agent-created work has no `parent_id` (`agent_work.py:17`). It writes to the board of the item it was `spawned_from`, followed to that chain's root, up to `agent_work.max_depth`.
  - **Membership** of a non-CrewSession board is resolved at read and write time and fails closed. Members are:
    - the root item's creator and assignee;
    - the assignees of its descendants;
    - for agent-created work, the requester and the `agent_work_watchers` (`workforce.py:1690-1695`);
    - the chief of the assignee's department;
    - the Captain.

    No one gains access to an existing board.
  - The key is a work item id from the first schema, so no later migration is needed.
- **A new kind, `failed_attempt`.** It records an approach its author tried and disproved. It is not a judgement on a peer's entry; that is what `challenge` is for.
  - **Fields:** `approach` (what was tried), `reason` (why it failed), at least one linked `evidence` or `artifact_ref` entry, and the declared `scope` (below).
  - **It may target an evaluator record.** It may reference the service-written `evidence` entry that #1337's CORAL attempts ledger records for a failed evaluated attempt. The ledger records *what* happened, written by the service; `failed_attempt` records *why*, written by the agent. Neither replaces the other.
  - **Contract checks.** The MASS output contract may require a `failed_attempt` from an attempt that ends `failed` by its own report (`TerminalStatus`, `src/probos/cognitive/elastic_team.py:151`). The structural checks gain two clauses: `failed_attempt` links evidence, and `failed_attempt` declares a scope.
  - **The service never writes a `failed_attempt`.** An attempt that crashes or times out leaves only the service-written outcome (AD-1231).
  - **Correcting one.** Like every entry, a `failed_attempt` can be challenged and superseded, never deleted. A `challenge` that targets it is the only way to clear it for a deliberate retry. No rule forbids a retry.
- **Every entry gets a headline.** It is a bounded `headline` beside the bounded body. Listings and deliveries carry only headlines, and the body is read by entry id.
- **Area claims stay on the work board.** This issue's `claim` keeps its meaning of an assertion of truth.
  - **Claiming an area means creating or taking a work item:** a self-task (`agent_work.py:299`), a pull claim, or a CrewSession plan step (AD-1192, `src/probos/work_item_steps.py`).
  - **Scope.** The work item gains an optional declared **scope**, stored under one nested metadata key that the board service owns. It is never a top-level key: the pull filter refuses several top-level keys (`workforce.py:10989-10999`).
    - The scope is a bounded set of tokens: `path:<repo-relative path>`, matched by prefix on `/` boundaries, and `area:<label>`, matched exactly after the `normalize_title` normalisation (`agent_work.py:123-125`).
    - **Overlap** is any intersection with the scope of another open item on the same board. It is computed deterministically when an item is claimed, when it is created, and when its scope changes.
  - **Overlap is advisory and never refuses a claim.** Both holders receive an overlap notice and resolve it themselves, for example by narrowing a scope or by recording a `question` and then a `decision`. A notice that neither holder acts on within a configured interval goes to the root's accountable owner: the CrewSession facilitator (`crew_session.py:1830`), otherwise the department chief of the root's assignee.
  - **Exclusive occupancy stays with AD-1159 work permits** (`src/probos/tools/work_permits.py:38-47`), which this amendment does not touch.
- **The claim shows related failures first.**
  - Every claim receipt includes the headlines and ids of the open `failed_attempt` entries on the same board whose scope intersects the claim's. This covers the pull receipt, the self-task result and step acceptance, and is bounded to N entries plus a count of the rest.
  - The claim records the ids it was shown. The agent decides what to do.
- **Urgent delivery during a turn** carries the matching `failed_attempt` entries and the overlap notices to each affected member.
  - **During a turn,** they arrive as one new block on the next outbound model request, alongside the three existing blocks (`agentic_loop.py:1749-1776`). Like them, the block is added to the outbound prompt and never to `messages`.
  - **A reader not in a turn** receives them at the start of its next turn.
  - **Each delivery is claimed before it is sent,** with `(owner_work_item_id, recipient, delivery_key)` as the key. This follows the claimed-notice pattern (`workforce.py:1696-1702`) in a table the board owns, created only when the feature is on. Delivery is therefore at most once per recipient, across overlapping runs and restarts.
  - **The block is labelled as peer-authored data.** It is filtered by membership and classification, can never carry an approval, and is bounded per request.
  - **Never to independent slots.** Slots declared `independence` (`elastic_team.py:255`), and review, verification and adjudication slots, receive no peer `failed_attempt` reasoning before they submit. This extends #1337's CORAL rule that workers read outcomes, not reasoning.
- **Configuration.** One config group with `failed_attempt_surfacing`, `overlap_notices` and `urgent_delivery`, each default `False`. With all three off, behaviour is exactly this issue's current behaviour.

### Added acceptance

- **CrewSession boards are unchanged.** A CrewSession-owned board keys on the session's work item id. The existing cross-board, membership-filtered-read and CrewSession-recovery tests pass unchanged, with the integration path running from A publish to B challenge to the authorized decision and then CrewSession recovery.
- **Non-CrewSession boards.**
  - A board on an ordinary root work item opens on the first member append.
  - A non-member append or read is refused before mutation.
  - A reference to another board's entry is refused, replacing "cross-session".
  - A descendant item (through `parent_id` or the `spawned_from` chain) writes to its root's board. A `spawned_from` chain beyond `max_depth` is refused.
- **`failed_attempt` contract.**
  - A `failed_attempt` without linked evidence or without a scope is refused before mutation, and each refusal has its own test.
  - A `failed_attempt` can be challenged and superseded. The superseded entry remains auditable, and reads report its current disposition.
  - No code path writes one on an agent's behalf.
- **Pre-claim surfacing.** A claim whose scope intersects an open `failed_attempt` returns that entry's headline and id in its receipt, and the claim records the id. A claim with no intersection returns none. The bound holds: N entries plus a count of the rest.
- **Overlap notices.**
  - Two open items on one board with intersecting scopes produce exactly one overlap notice per holder, and both claims succeed.
  - Path tokens match only on `/` boundaries, so `src/a` does not overlap `src/ab`.
  - An unresolved notice escalates once, to the accountable owner, after the configured interval.
- **Urgent delivery.**
  - An entry or notice appended while a member's turn is running reaches that member on the next model request after the current tool round. The test crosses the seam: worker A appends, then the next request of worker B's running loop contains the block.
  - Restart and overlapping delivery runs never deliver it twice.
  - An independence-declared or review slot receives no peer `failed_attempt` before it submits.
  - The block is absent from `messages`.
- **Default off is exact.** With all three flags off, a board behaves as before this amendment. No delivery table is created, and no claim receipt changes.
- **Measured trial, the gate for any default.**
  - **The scenario** is fixed, seeded and enrolled. For elastic teams it is an AD-1290 (#1337) Team Trials arm on the financial-close fixture. For ordinary work items it is a Ship Trials scenario under AD-1186 (#1123).
  - **Planted conditions.** The scenario plants at least one dead end (an approach that fails a known check) and at least one pair of overlapping areas.
  - **Arms:** control (all off); full; no-surfacing; no-overlap-notice; and turn-start-only delivery (no urgent delivery).
  - **Measures, per arm:**
    - **retried-failure count:** attempts that fail a planted dead end's check after a `failed_attempt` for it was on the board;
    - **duplicated-attempt count:** pairs of concurrently open items with intersecting scope that both completed the same planted sub-task;
    - **total tokens;**
    - **contract-pass outcome.**
  - **Runs.** At least 5 seeded runs per arm, reported as mean and range.
  - **Turning a flag on by default.** It needs a recorded reduction outside the control arm's range, no regression in outcome, and the token cost stated. Turning it on is a governed decision.

### Do Not Build (added)

- No removal of the chain of command or of central coordination. Agensh's orchestrator-free design is not adopted.
- No autonomous mode without escalation. Agensh's "fully autonomous ... do not ask what to do next" rule is rejected.
- No 1,024-agent or agent-count scaling claim, and no work justified by it.
- No exclusive area locks on the board. Exclusivity stays with AD-1159 work permits.
- No rule against retrying. A `failed_attempt` is cleared only by a challenge.
- No delivery through the Ward Room. No keyword search over the board history in this amendment (considered, deferred).

---

## Part B — not for posting

### Decision required from the Captain

**Condition met:** "changing the product objective beyond the existing issue" (`.github/agents/orchestrator.agent.md:121`).

#1336's Decision says the board is "owned by the durable CrewSession/team instance". Letting an ordinary work item own one extends that objective. The Captain's 2026-10-28 direction ("the home is the existing work board / task management, extended, via an amendment to #1336") points this way, but it does not explicitly settle ownership. So the ratification should be explicit, and it can be given in the same approval that posts this amendment.

**Not a Captain condition:**
- Keying CrewSession boards to the work item id. The id is the same string (`crew_session.py:6130`), and #1336 is unbuilt (see Absence Verified), so no persisted schema changes.
- Authorization is not weakened. Membership fails closed, and no existing board gains a reader.

**Options, ranked:**

1. **Recommended: own by any root work item, with a CrewSession as one owner kind** (this draft).
   - *Gained:* ordinary crew work gets the board now. That is the path that runs today, while elastic teams are inert until AD-1288.
   - *Given up:* #1336 grows a membership resolver for non-CrewSession boards.
   - *Controls:* no security, governance or audit control is weakened.
2. **Fallback, fully in the envelope: key by work item id, but enable only `crew_session` owners.** The work-item key is in the schema from day one, so there is no migration later. Ordinary items stay closed until the Captain ratifies.
   - *Given up:* the Agensh mechanisms reach no live work until AD-1288 lands.
3. **Keep the board owned by CrewSession only, as written.**
   - *Given up:* the same as option 2, plus a schema migration later if the Captain widens it then. That migration would itself become a persisted-schema Captain condition.

**Exact decision:** "Approve posting the Agensh amendment to #1336, including ownership by any root work item (option 1)". Or: "post it with option 2". If the Captain does not decide, the orchestrator applies option 2.

### Effects on dependent issues

- **AD-1288 (#1335).** No change. Attempts bind to durable work under the same session id.
- **AD-1290 (#1337).**
  - Gather and the CORAL ledger read the same board id.
  - The no-blackboard ablation is unaffected.
  - The trial arms above are added to Team Trials. When this amendment is posted, put a one-line cross-reference on #1337; it is not a second amendment.
- **AD-1310 (#1361) HXI consumer.** `failed_attempt` joins the canvas's object list. Overlap notices are delivery items, not board entries, so they are not canvas objects.
- **AD-1348 (#1630, paused).** No collision. This amendment never touches `tools/work_permits.py`. The baseline rows `WorkPermit` and `WorkPermitStore`, staged under AD-1348, stay as they are.

### Numbering

No new AD or BF is allocated: this is an amendment to AD-1289. `scripts/ad_ceiling.py` was not run, because nothing depends on a new number.

## Verified Against Codebase (2026-10-28)

All checks were run against HEAD `791d15fc` of this worktree, which matches `origin/main` and includes PRs #1692 and #1693. The `src/probos/config.py` anchor was re-checked at this HEAD and is unchanged. No other anchored file changed since the first pass at `65f5e02b`.

```
gh api repos/seangalliher/ProbOS/issues/1336 --jq .body
  Decision: "Add a typed mission blackboard owned by the durable CrewSession/team instance"
  Kinds: claim, evidence, challenge, decision, dissent, question, artifact_ref
  Amendment (2026-10-11) MASS: WorkerSlot.output_contract, ElasticTeamSpec.hops, "The service checks shape, never quality"

gh api repos/seangalliher/ProbOS/issues/1337 --jq .body
  Amendment (2026-10-25) CORAL: "Attempts ledger ... one blackboard evidence entry per evaluated attempt ... These use existing AD-1289 entry kinds; no new kind is added."
  "Workers read outcomes, not reasoning." independence-declared slots read no peer claim before they submit

gh api repos/seangalliher/ProbOS/issues/1336/comments
  2026-09-07 "Spatial collaboration consumer": AD-1310/#1361 renders claim, evidence, challenge, question, dissent, decision, artifact-reference objects

grep -n 'work_type != "crew_session"\|metadata.get("crew_session")' src/probos/cognitive/crew_session.py
  2542: if parent is None or parent.work_type != "crew_session":
  2544: session = self._parse_contract(parent.metadata.get("crew_session"))

grep -n "session_id=parent.id" src/probos/cognitive/crew_session.py
  6130: session_id=parent.id,

grep -n "facilitator_id\|success_criteria" src/probos/cognitive/crew_session.py
  1830: facilitator_id: str
  1832: success_criteria: tuple[str, ...]

grep -n "^TerminalStatus\|independence: IndependencePolicy\|^class WorkerSlot" src/probos/cognitive/elastic_team.py
  151: TerminalStatus = Literal["succeeded", "failed", "cancelled"]
  247: class WorkerSlot(_Frozen):
  255: independence: IndependencePolicy

grep -n "CREATE TABLE IF NOT EXISTS" src/probos/workforce.py
  1393: CREATE TABLE IF NOT EXISTS work_items (
  1690: CREATE TABLE IF NOT EXISTS agent_work_watchers (
  1696: CREATE TABLE IF NOT EXISTS agent_work_notices (
  (1701: PRIMARY KEY (work_item_id, recipient, kind))

grep -n "due_at REAL\|verification TEXT" src/probos/workforce.py
  1406: due_at REAL,
  1414: verification TEXT NOT NULL DEFAULT '{}',

grep -n "def _standalone_pull_item" src/probos/workforce.py
  10989: def _standalone_pull_item(item: WorkItem) -> bool:
  (10991-10999: refuses crew_session, parent_id, and metadata keys crew_session, crew_execution, thread_id, room_id, session_id)

grep -n "^NOTICE_\|^KIND_\|def normalize_title\|def create_self_task\|def claim_allowed\|def claim_notice" src/probos/agent_work.py
  52: KIND_SELF: Final = "self"
  56: NOTICE_TERMINAL: Final = "terminal"
  123: def normalize_title(title: str) -> str:
  299: async def create_self_task(
  445: def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
  490: async def claim_notice(self, work_item_id: str, recipient: str) -> bool:
  (347-348: "An open request with the same department, tool and normalised title is returned instead, and the requester becomes its watcher.")
  (17: agent work carries no parent_id; the pull filter would refuse it)

grep -n "class AgentWorkConfig\|enabled: bool = False" src/probos/config.py   (re-checked at 791d15fc)
  3572: class AgentWorkConfig(BaseModel):
  3580: enabled: bool = False

grep -n "async def deliver_due_notices\|async def _post\|create_post" src/probos/agent_work_runner.py
  393: async def deliver_due_notices(self) -> int:
  595: async def _post(self, item: WorkItem, record: AgentWorkRecord, body: str) -> bool:
  601: await self._ward_room.create_post(

grep -n "@router.post(\"/work-items/claim\")" src/probos/routers/workforce.py
  388: @router.post("/work-items/claim")
  389: async def claim_work_item(

grep -n "_register_work_item_pull_tools(" src/probos/startup/communication.py
  215: def _register_work_item_pull_tools(
  859: _register_work_item_pull_tools(        (registered in production; not dormant)

grep -n "request_system_prompt = " src/probos/cognitive/swe_harness/agentic_loop.py
  1749: request_system_prompt = effective_system_prompt
  1751: request_system_prompt = (                       (budget awareness note)
  1761: request_system_prompt = f"{request_system_prompt}\n\n{economic_block}"   (AD-1322)
  1776: request_system_prompt = f"{request_system_prompt}\n\n{_plan.block}"      (AD-1324)
  (1754: "AD-1322: informs only; appended to the outbound prompt, never to ``messages``.")

grep -n "AgenticLoop(" src/probos
  cognitive/agentic_dispatch.py:4057: loop = AgenticLoop(
  cognitive/swe_harness/native_builder.py:139: loop = AgenticLoop(

Read src/probos/tools/work_permits.py lines 1-50
  38-47: "Single holder. At most one open, unexpired permit per (session_id, workstation_id)" ; "issued_by == holder_id is rejected"

grep -n "WorkPermit\|ElasticCommissionService\|CommunicationContagionFirewall" docs/development/dormant-class-baseline.yaml   (merged in PR #1692)
  49:  cognitive/elastic_commission.py::ElasticCommissionService:  staged, owner AD-1288 (#1335)
  406: security/contagion.py::CommunicationContagionFirewall:      wire, owner '#1324'
  454: tools/work_permits.py::WorkPermit:                          staged, owner AD-1348 (#1630)
  457: tools/work_permits.py::WorkPermitStore:                     staged, owner AD-1348 (#1630)
```

## Absence Verified (2026-10-28)

```
CLAIM: no blackboard implementation exists yet (#1336 unbuilt; no persisted schema to migrate)
RUN:   Grep -i "blackboard" src/probos
FOUND: 0 matches
HOLDS: yes

CLAIM: agent-work notices have one kind only, terminal
RUN:   Grep "^NOTICE|^KIND_|^OUTCOME_" src/probos/agent_work.py
FOUND: 52-54 KIND_*, 56 NOTICE_TERMINAL, 57 OUTCOME_EXPIRED
HOLDS: yes, NOTICE_TERMINAL is the only notice kind

CLAIM: the crew loop's only per-request injection points are the budget note, AD-1322 and AD-1324
RUN:   Grep "request_system_prompt = " agentic_loop.py; Grep "messages\.append\(" agentic_loop.py
FOUND: 1749, 1751, 1761, 1776; messages.append at 2075, 2079, 2206 (assistant turn and tool results)
HOLDS: yes, for AgenticLoop. Whether any other channel reaches a running turn was not enumerated
       beyond this loop.

CLAIM: the dormant-class baseline has no work-item pull tool rows (the caller's premise said it did)
RUN:   read the whole of dormant-class-baseline.yaml (first pass, from branch
       origin/feat/ad1270-dormant-classes-20261027-65f5e02b); re-checked at 791d15fc, where it is
       merged (PR #1692): Grep "WorkPermit|AD-1348"
FOUND: rows naming AD-1348 are exactly WorkPermit (454) and WorkPermitStore (457); no row names
       work_item_pull_tool
HOLDS: yes. The pull tools are registered at startup (communication.py:859). There is no collision
       with AD-1348 while area claims stay advisory and never use work permits.
```

### Not verified

- **DeLM (arXiv 2606.10662).** It was not read: arxiv.org is outside this session's allowed network domains.
- **The Agensh source** (`board-service`). Only the README was read, so the caps and delivery behaviour come from the paper's Appendix A and B, not from the code.
