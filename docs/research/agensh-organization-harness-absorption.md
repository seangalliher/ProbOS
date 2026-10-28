# Agensh Absorption: Self-Organized Multi-Agent Harness

*Sean Galliher, 2026-10-28*
*Source: "Agensh: Scaling Organizational Intelligence to 1,024 Agents" (Zhan, Song, Dong, Huang, Lian, Xia, Wei; Microsoft Research), arXiv 2609.26781, 2026-09-22. Read in full from the PDF (13 pages, appendices A-C included).*
*Repository: [github.com/microsoft/Agensh](https://github.com/microsoft/Agensh) (MIT; README only was read).*
**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

## Purpose

This note records what ProbOS takes from Agensh, what it rejects, and where each idea lives. The Captain set the scope on 2026-10-28: the ideas go to the work board and the typed mission blackboard, AD-1289 (#1336), as an amendment. They do not go to the Ward Room, which is a social board. The amendment text is in `docs/research/agensh-amendment-1336-draft.md`.

## What Agensh is

Agensh runs many copies of one worker over shared infrastructure, with **no central orchestrator**. Each worker repeats a five-step loop (paper section 2.1): gather context, claim a sub-task, act, verify against the acceptance criteria, merge. The infrastructure has three parts (section 2.2):

- **Shared workspace:** Gitea. There is one issue per area a worker takes, and pull requests carry the merges.
- **Message interface:** Mattermost. There is one task channel, plus direct messages.
- **Shared context board:** an append-only log of short typed entries, adapted from DeLM (Mao and Mirhoseini, arXiv 2606.10662).

The worker prompt is in Appendix A. The entry kinds are:

- `OBSERVED`: reference behaviour the worker noticed.
- `FACT`: something it confirmed.
- `FAIL`: "a hypothesis you falsified (the highest-value entry: it stops peers spending budget on it)".
- `CLAIM`: an area it is working on.
- `PATCH_SUMMARY`: `files= | idea= | evidence=`.

Entries are capped at 100 characters, or 300 for `PATCH_SUMMARY`. A longer version goes in `detail`, which `board_unfold` returns. `board_read` returns the latest 2,000 entries, and `board_grep` runs AND/OR keyword search over the whole history. Two rules sit in the prompt: "Do not re-derive a peer's `FACT`, and do not retry something recorded as `FAIL`."

**Delivery** (Appendix B):

- At turn start, the worker receives queued workspace notices, channel messages and recent board entries.
- During a turn, a wrapper around each *infrastructure* (MCP) tool call adds pending direct messages and new board entries to that call's result. It "does not interrupt an arbitrary running process".
- The prompt tells the worker how to react to an entry that arrives mid-turn:
  - a `FAIL`: stop if you are doing that thing;
  - a `CLAIM` on what you are building: settle the collision by direct message;
  - any other `CLAIM`: keep going.
- After 10 idle minutes, a worker is prompted to keep working. A turn that publishes no board entry is followed by a reminder to publish.

## Evidence assessment

The Captain's reading was checked against the PDF.

| Claim | Verdict | Where |
|---|---|---|
| No ablations | **Confirmed.** Only the agent count varies (1, 8, 32 and 128 agents, plus 1,024 on pandoc). No mechanism is removed, including the board, `FAIL`, claims and mid-turn delivery. | §3.1, Figs 1, 5 and 6 |
| Compute not normalized | **Confirmed.** Every configuration has the same 6-hour wall clock, and each worker is its own GPT-5.6-sol session (272K input tokens). No token or cost figures are given. Start-up is staggered: one agent every 30 s in the first hour, then one every 3 s. So at 1,024 the last worker starts about 1 h 45 min in, and the compute is "hundreds of times" the single agent's rather than exactly 1,024×. | §3.1; App. C |
| Single runs, no variance | **No run count, error bars or seeds are reported.** Several curves are not monotonic, which is consistent with noise of a few points: ctags is 25.82% with 1 agent and 18.47% with 8; FFmpeg is 13.22% at 32 and 12.89% at 128; gromacs reads 19.69, 19.37 and 19.37 across 1, 8 and 32. | Fig. 5 |
| Asymmetric continuation mechanisms | **Confirmed.** The single-agent baseline has a stop hook. Teams have a 10-minute idle detector. The prompts are almost identical, but the triggers differ: the hook fires at every stop, while teams can sit idle for 10 minutes. This confounds the 1-versus-N comparison, in an unknown direction. | App. C |
| Emergent cooperation is anecdotal | **Confirmed.** It consists of narrative examples per scale, with no counts and no coding scheme. | §3.2 |
| Narrow scope | **Confirmed.** One model (GPT-5.6-sol, high effort) on one harness (Copilot), five ProgramBench tasks, and 1,024 agents only on pandoc. | §3, App. C |
| *Added:* diminishing returns | Going from 128 to 1,024 agents on pandoc (8× the agents) adds 4.12 points (50.94 to 55.06). The 5-task mean at 128 agents is 28.78%. | §3.1 |
| *Added:* autonomy is a precondition of the setup | The prompt's iron rule 1 reads: "Fully autonomous ... do not wait for instructions, do not ask on mattermost 'what to do next'". | App. A |

**What the paper does and does not show.** It shows that, on these tasks, more workers on this harness reached higher scores within a fixed wall clock. It shows nothing about which mechanism contributed. In particular, there is no evidence that `FAIL` entries, claims or mid-turn delivery help on their own. ProbOS therefore takes the mechanisms as **design hypotheses** and gives them their own measured acceptance. It does not borrow the paper's numbers.

## Per-mechanism decisions

| # | Agensh mechanism | Decision | ProbOS anchor (verified 2026-10-28) | Owner |
|---|---|---|---|---|
| 1 | `FAIL`: a falsified approach, "the highest-value entry" | **Absorb as a new kind, `failed_attempt`.** #1336's `challenge` and `dissent` target another entry, and nothing records an author's own disproved approach. A distinct kind is needed because reads filter by kind (#1336 Decision), and the surfacing rule in row 3 keys on it. It must link evidence (MASS contract checks). It can be challenged and superseded, never deleted. | #1336 Decision (kinds list); `elastic_team.py:151` (`TerminalStatus` includes `failed`); #1337 CORAL ledger (service-written `evidence` per evaluated attempt) | #1336 amendment |
| 2 | "Do not retry anything recorded as `FAIL`" | **Adapt.** An absolute ban turns one wrong `FAIL` into a pruned search branch for everyone. Instead, the entry is surfaced before the claim and the claim records which entries it was shown. To retry, the agent challenges the entry first (`challenge` targeting the `failed_attempt`). The agent decides; the service records (AD-1231). | #1336 Decision (`challenge` with target reference) | #1336 amendment |
| 3 | Mid-turn delivery of a new `FAIL` or `CLAIM` | **Adapt.** A `failed_attempt` or an overlap notice that matches the reader's declared scope is added as a block to the reader's next model request, between tool rounds. This uses the per-request injection seam the loop already has: the budget note, the AD-1322 economic block and the AD-1324 tier block are all appended to the outbound system prompt, "never to `messages`". Delivery is tracked by a per-reader cursor, so it is at-least-once and idempotent over immutable entry ids. Delivered text is labelled as peer-authored data, not instructions. | `agentic_loop.py:1749-1776`; `agentic_dispatch.py:4057` (crew loop construction) | #1336 amendment |
| 4 | `CLAIM` = "I am taking this area" | **Keep it on the work board, not the blackboard.** In #1336, `claim` means an assertion of truth, so the board's `claim` kind is not overloaded. An area claim *is* a work item: a self-task, a pull claim, or a plan step owned by a CrewSession. The amendment adds only an optional declared **scope** on the work item and an advisory **overlap notice**. Exclusive occupancy stays with AD-1159 work permits, which are mutual-exclusion grants issued by a second authority. This keeps clear of AD-1348's planned use of permits. | `agent_work.py:299` (`create_self_task`), `:347-348` (exact-title dedup of requests), `:445` (`claim_allowed`); `routers/workforce.py:388-402`; `tools/work_item_pull_tool.py:1`; `work_item_steps.py:1`; `tools/work_permits.py:38-47` | #1336 amendment |
| 5 | Claim overlap settled by direct message | **Adapt.** Both holders receive the overlap notice, and they resolve it themselves. If neither yields, the notice escalates to the owner of the parent work item through the chain of command, not to a peer vote. | the same as row 4 | #1336 amendment |
| 6 | Turn-start delivery of channel posts | **Already present; not adopted for the board.** The Ward Room remains the social channel, by the Captain's direction. | `agent_work_runner.py:393-414`, `:595-615` (terminal notices are Ward Room posts) | none |
| 7 | Short capped entries plus `detail` / `board_unfold` | **Absorb.** A bounded `headline` is added beside the bounded body, and deliveries and listings carry only the headline. A reader fetches the body by entry id. #1336 already bounds bodies; this only makes delivery cheap. | #1336 Decision ("bodies are strictly bounded") | #1336 amendment |
| 8 | `PATCH_SUMMARY` (files, idea, evidence) | **Reject as a kind; already covered.** It maps to `evidence` plus `artifact_ref`, and MASS's output contract already requires a `claim` to link `evidence` before an attempt can complete. | #1336 MASS amendment | none |
| 9 | `OBSERVED` / `FACT`; "do not re-derive a peer's `FACT`" | **Map to the existing kinds; reject the rule.** `OBSERVED` and `FACT` map to `evidence` and `claim`. In ProbOS a claim never becomes true by repetition; only an accepted `decision` does. "Do not re-derive" conflicts with slots declared `independence`. | #1336 Decision; `elastic_team.py:255`; #1337 CORAL amendment | none |
| 10 | Verify against the acceptance criteria before merge | **Already present.** | `workforce.py:1414` (`verification` column); `crew_session.py:1832` (`success_criteria`); MASS output contract on #1336 | none |
| 11 | Reminder when a turn publishes no entry | **Reject as a separate mechanism.** The MASS output contract already refuses completion and names the unmet clause, and CORAL reflection checkpoints (#1337) cover long-running attempts. A third nudge would duplicate them. | #1336 MASS amendment; #1337 CORAL amendment | none |
| 12 | `board_grep` over the full history | **Considered, deferred.** ProbOS reads are already cursor-paged over the full history and filtered by kind, slot/task and (with this amendment) scope. Keyword search waits until a trial shows that scope filtering misses related entries. | #1336 Decision (bounded filtered reads) | none |
| 13 | Idle nudge; T-45 and T-5 wrap-up reminders | **Considered, deferred.** Deadline-aware wrap-up could use `due_at` (`workforce.py:1406`), but it is outside this amendment. | — | none |
| 14 | No central orchestrator; iron rule "fully autonomous" | **Reject.** Chain of command, escalation to the Captain, and governed decisions stay. | — | Do Not Build |
| 15 | Agent count as a scaling dimension (1,024 workers) | **Reject as a claim.** It is unablated and the compute is not normalized (see the assessment). | — | Do Not Build |

## Blind spots the paper does not discuss

1. **A wrong `FAIL` poisons the search.** The entry Agensh values most is also the riskiest one. That is why row 2 replaces the ban with surfacing and a challenge path, and why a `failed_attempt` must carry evidence and a specific scope.
2. **Board text injected mid-turn is a prompt-injection channel.** It is peer-written content landing in another agent's prompt. It is delivered as labelled data, filtered by classification, and can never carry an approval. This follows the same rule Claude Code agent teams apply to messages between agents. `security/contagion.py` (`CommunicationContagionFirewall`) is listed for wiring under #1324; this is one more consumer that firewall should cover.
3. **Independence.** A review, verification or adjudication slot, or a slot declared `independence`, must not receive peers' `failed_attempt` reasoning before it submits. This extends the CORAL rule that "workers read outcomes, not reasoning" on #1337.
4. **Cost.** Every row that adds delivery adds tokens. The amendment's trials report tokens per arm, which is the comparison the paper never makes.
5. **HXI consumer.** AD-1310 (#1361) renders the board's kinds on the spatial canvas (comment on #1336, 2026-09-07), so `failed_attempt` has to be added to its object list.

## Prior art considered (bounded, 2026-10-28)

- **DeLM** (arXiv 2606.10662), the origin of Agensh's shared context: arxiv.org is not reachable from this session, so the paper was not read. It is recorded here as a lead, not as evidence.
- **Claude Code agent teams** ([docs](https://code.claude.com/docs/en/agent-teams)), checked 2026-10-28:
  - Claiming is exclusive and uses file locking. ProbOS keeps exclusivity in work permits and makes area overlap advisory. Adapted.
  - A `TaskCompleted` hook can block completion, which is the same shape as the MASS output contract. Nothing new.
  - Messages between agents are treated as untrusted and cannot relay an approval. Absorbed as blind spot 2.
- **Reference projects** (`reference-projects.md`, judged on 2026-10-28): the Claude Code row is up to date (2026-10-16), so this check is recorded beside it. AutoGen and CrewAI are *passing* rows and therefore count as never reviewed. They were considered and deferred: the paper does not cite them for these mechanisms.

## Open question for the Captain

**May an ordinary work item, one that is not a CrewSession, own a blackboard?** The amendment keys the board to a work item id. For a CrewSession this changes nothing, because a CrewSession *is* a parent work item (`work_type == "crew_session"`, `crew_session.py:2542-2544`) and its session id is that item's id (`crew_session.py:6130`). For any other work item, this extends #1336's objective beyond elastic teams. The amendment draft records the recommendation and the exact decision.
