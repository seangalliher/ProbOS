# Agensh Absorption: Self-Organized Multi-Agent Harness

*Sean Galliher, 2026-10-28*
*Source: "Agensh: Scaling Organizational Intelligence to 1,024 Agents" (Zhan, Song, Dong, Huang, Lian, Xia, Wei; Microsoft Research), arXiv 2609.26781, 2026-09-22. Read in full from the PDF (13 pages, appendices A-C included).*
*Repository: [github.com/microsoft/Agensh](https://github.com/microsoft/Agensh) (MIT; README only was read).*
**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

## Purpose

This note records what ProbOS takes from Agensh, what it rejects, and why. Its main job is to stop the rejected mechanisms being proposed again.

**Outcome (Captain, 2026-10-28):** ProbOS takes only one idea. A disproved approach is recorded on the CrewSession's blackboard, as `evidence` with a `disproved` marker, so that teammates see it before they repeat it. This is a short amendment to AD-1289 (#1336); the draft is in `docs/research/agensh-amendment-1336-draft.md`. Nothing goes to the Ward Room, which is a social board.

**Why so little.** Persistent crew already collaborate on one task through CrewSession (AD-1124 to AD-1133):

- the plan is decomposed (`crew_orchestrator.py:23`: resolve, delegate, fan-out, verify, synthesize);
- sub-tasks are assigned by capability × trust × department (AD-864, `crew_assignment.py:1`);
- ingress is deduplicated (AD-1128, `DECISIONS.md:2525`);
- results are finalized only once verified (AD-1126, `crew_finalizer.py:1`).

Agensh's claiming, overlap and self-assignment machinery makes up for having no planner. ProbOS has one, and #1336 already gives each CrewSession its own board.

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

**What the paper does and does not show.** It shows that, on these tasks, more workers on this harness reached higher scores within a fixed wall clock. It shows nothing about which mechanism contributed. In particular, there is no evidence that `FAIL` entries, claims or mid-turn delivery help on their own. ProbOS therefore borrows none of the paper's numbers. It adopts only the one mechanism that is cheap and fits the CrewSession board: recording disproved approaches.

## Per-mechanism decisions

| # | Agensh mechanism | Decision | ProbOS anchor (verified 2026-10-28) | Owner |
|---|---|---|---|---|
| 1 | `FAIL`: a falsified approach, "the highest-value entry" | **Absorb, minimally.** It becomes `evidence` with the marker `disproved: true` and a link to at least one supporting entry, written only by an agent. No new kind is added, following the precedent of #1337's CORAL amendment ("no new kind is added"); a marker can be filtered on without every consumer learning a kind. Teammates in the same CrewSession receive the session's current `disproved` entries in the bounded read at the start of an attempt. Independence-declared, review, verification and adjudication slots do not receive them until they submit. | #1336 Decision (kinds list); `elastic_team.py:255`; #1337 CORAL amendment | #1336 amendment |
| 2 | "Do not retry anything recorded as `FAIL`" | **Adapt: no ban.** A ban would turn one wrong `FAIL` into a dead branch for everyone. To retry deliberately, an agent first files a `challenge` that targets the entry. | #1336 Decision (`challenge` with target reference) | #1336 amendment |
| 3 | Mid-turn delivery of a new `FAIL` or `CLAIM` | **Rejected (Captain, 2026-10-28).** Teammates in one CrewSession work on sub-tasks that the planner assigned, so a disproved approach seen at the start of an attempt is enough. Delivery mid-turn would need a delivery table, a new prompt block and a new prompt-injection surface, and nothing in the paper shows it pays for that. *Do not re-propose without a measured duplicate-work problem inside a CrewSession.* | `agentic_loop.py:1749-1776` (the per-request blocks it would have joined) | none |
| 4 | `CLAIM` = "I am taking this area", made before the work | **Rejected (Captain, 2026-10-28). CrewSession already decomposes and assigns, so claims and overlap checks are not needed.** Agensh workers claim because there is no planner. In ProbOS, the CrewSession plan decomposes the task (`crew_orchestrator.py:23`) and AD-864 assigns each sub-task by capability × trust × department (`crew_assignment.py:1`). Exclusive occupancy, where it matters, is AD-1159 work permits (`tools/work_permits.py:38-47`). Note also that #1336's `claim` means an assertion of truth, not "I am taking this". *Do not re-propose area claims, declared scope or overlap notices.* | `crew_orchestrator.py:23`; `crew_assignment.py:1`; `tools/work_permits.py:38-47` | none |
| 5 | Claim overlap settled by direct message | **Rejected with row 4.** No overlap arises when sub-tasks are assigned by the planner. | as row 4 | none |
| 5a | Re-keying the board to any work item, so that ordinary crew work can have one | **Rejected (Captain, 2026-10-28).** The board stays CrewSession-owned, as #1336 is written. Each CrewSession already has its board, and crew who work together on one task do so through a CrewSession. | #1336 Decision | none |
| 6 | Turn-start delivery of channel posts | **Already present; not adopted for the board.** The Ward Room remains the social channel, by the Captain's direction. | `agent_work_runner.py:393-414`, `:595-615` (terminal notices are Ward Room posts) | none |
| 7 | Short capped entries plus `detail` / `board_unfold` | **Already covered.** #1336 already bounds every body. The separate headline was only needed for mid-turn delivery, which was rejected. | #1336 Decision ("bodies are strictly bounded") | none |
| 8 | `PATCH_SUMMARY` (files, idea, evidence) | **Reject as a kind; already covered.** It maps to `evidence` plus `artifact_ref`, and MASS's output contract already requires a `claim` to link `evidence` before an attempt can complete. | #1336 MASS amendment | none |
| 9 | `OBSERVED` / `FACT`; "do not re-derive a peer's `FACT`" | **Map to the existing kinds; reject the rule.** `OBSERVED` and `FACT` map to `evidence` and `claim`. In ProbOS a claim never becomes true by repetition; only an accepted `decision` does. "Do not re-derive" conflicts with slots declared `independence`. | #1336 Decision; `elastic_team.py:255`; #1337 CORAL amendment | none |
| 10 | Verify against the acceptance criteria before merge | **Already present.** | `workforce.py:1414` (`verification` column); `crew_session.py:1832` (`success_criteria`); MASS output contract on #1336 | none |
| 11 | Reminder when a turn publishes no entry | **Reject as a separate mechanism.** The MASS output contract already refuses completion and names the unmet clause, and CORAL reflection checkpoints (#1337) cover long-running attempts. A third nudge would duplicate them. | #1336 MASS amendment; #1337 CORAL amendment | none |
| 12 | `board_grep` over the full history | **Considered, deferred.** ProbOS reads are already cursor-paged over the full history and filtered by kind and slot/task. One CrewSession's board is small enough for that. | #1336 Decision (bounded filtered reads) | none |
| 13 | Idle nudge; T-45 and T-5 wrap-up reminders | **Rejected.** The CrewSession lifecycle and its verified finalization (AD-1126, `crew_finalizer.py:1`) own pacing and completion. Deadline-aware wrap-up through `due_at` (`workforce.py:1406`) is a separate question. | — | none |
| 14 | No central orchestrator; iron rule "fully autonomous" | **Reject.** Chain of command, escalation to the Captain, and governed decisions stay. | — | Do Not Build |
| 15 | Agent count as a scaling dimension (1,024 workers) | **Reject as a claim.** It is unablated and the compute is not normalized (see the assessment). | — | Do Not Build |

## Blind spots the paper does not discuss

1. **A wrong `FAIL` poisons the search.** The entry Agensh values most is also the riskiest one. That is why row 2 replaces the ban with a challenge path, and why a `disproved` entry must link evidence.
2. **Peer text in another agent's prompt is an injection channel.** This was one reason to reject mid-turn delivery (row 3). Entries that are read at the start of an attempt are still peer-written data, not instructions.
3. **Independence.** A review, verification or adjudication slot, or a slot declared `independence`, must not receive peers' `disproved` reasoning before it submits. This extends #1337's CORAL rule that "workers read outcomes, not reasoning".
4. **Cost.** Every delivery mechanism adds tokens. The paper reports none, and this was another reason to keep only the read at attempt start.
5. **HXI consumer.** No change for AD-1310 (#1361). No kind is added, so the canvas's object list is unchanged.

## Prior art considered (bounded, 2026-10-28)

- **DeLM** (arXiv 2606.10662), the origin of Agensh's shared context: arxiv.org is not reachable from this session, so the paper was not read. It is recorded here as a lead, not as evidence.
- **Claude Code agent teams** ([docs](https://code.claude.com/docs/en/agent-teams)), checked 2026-10-28:
  - Claiming is exclusive and uses file locking. Not needed here: in ProbOS the CrewSession planner assigns the sub-tasks, and exclusive occupancy is AD-1159 work permits.
  - A `TaskCompleted` hook can block completion, which is the same shape as the MASS output contract. Nothing new.
  - Messages between agents are treated as untrusted and cannot relay an approval. Absorbed as blind spot 2.
- **Reference projects** (`reference-projects.md`, judged on 2026-10-28): the Claude Code row is up to date (2026-10-16), so this check is recorded beside it. AutoGen and CrewAI are *passing* rows and therefore count as never reviewed. They were considered and deferred: the paper does not cite them for these mechanisms.

## Ownership question (resolved)

**Resolved by the Captain, 2026-10-28:** the board stays CrewSession-owned, as #1336 is written. A first draft proposed keying the board to any root work item, so that ordinary crew work could have one. It was declined: crew who work together on one task do so through a CrewSession, and each CrewSession already has its board. Nothing was widened, so no ratification was needed.
