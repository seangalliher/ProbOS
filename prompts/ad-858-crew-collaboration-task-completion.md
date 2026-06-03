# AD-858..862 — Crew Collaboration: coordinated multi-agent task completion (decompose → fan-out → adversarial-verify → converge → synthesize)

**Status:** Draft for review (Architect-authored, verify-first against HEAD)
**Mode:** Architect spec. Builder executes ONE AD = ONE commit with a gate between each. Do NOT build the whole epic in one pass.
**Northstar:** Crew agents complete *hard* work the way a ship's crew does — a single goal is decomposed into a sub-task DAG, fanned out across **persistent, trusted, memory-bearing** crew agents, each result is **independently/adversarially verified** before it folds in, the crew **iterates until results converge**, and the verified parts are **synthesized into one completion** with per-agent attribution recorded against the durable trust ledger.
**Numbering:** Highest reserved AD = **AD-857** (Crew Self-Unblock epic). This epic = **AD-858–862**. Reconciled in `docs/development/roadmap.md` (Crew Autonomy table).
**Depends on:** **AD-856** (AgenticLoop as the dispatchable-work-item executor) — each subtask in this epic runs through that executor. Build 856 first.

---

## Why this epic (the gap)

ProbOS already owns the **substrate** for coordinated multi-agent work, but it has never been wired into a single "complete this hard task by collaboration" loop. The connective tissue and two genuinely-missing pieces (a semantic LLM decomposer and an adversarial **convergence gate**) are this epic.

| Existing primitive | Location (verified HEAD) | What it already does | What it does NOT do |
|---|---|---|---|
| `ParallelDispatcher` (AD-594c) | `consultation/dispatch.py:283`, `dispatch()` at `:405` | Decomposes a plan → `WorkItemSpec` DAG, detects resource conflicts, injects serialization edges, creates `WorkItem`s with `depends_on` + `assigned_to`, tracks progress/blockers | Decomposer is **markdown-only** (`MarkdownPlanDecomposer:189`); no LLM/semantic decomposition of a single goal |
| `PlanDecomposer` Protocol | `consultation/dispatch.py:162` | Pluggable decomposer seam — docstring says *"LLM-driven semantic decomposers plug in here under a separate AD"* | The LLM decomposer itself does not exist yet — **this is the hook for AD-858** |
| `WorkItem` WBS containment | `workforce.py:571` (`parent_id`), `depends_on` | Parent/child + dependency DAG already modeled | No driver that runs a parent as "collect verified children → synthesize" |
| `RedTeamAgent` | `agents/red_team.py:25`, `verify()` at `:66` | **Deterministic** re-execution + compare for specific tool intents (`read_file`/`stat_file`/`run_command`/`http_fetch`/`write_file`); reports discrepancies to trust + consensus | Does NOT do **semantic** task-result verification (judging whether a synthesized answer/work product is correct) |
| `compute_shapley_values` | `consensus/shapley.py:37` | Per-agent Shapley attribution over `list[Vote]` for a consensus outcome | Not yet applied to multi-agent *task* contribution |
| `DAGExecutor` | `cognitive/decomposer.py:668` | Parallel intent execution respecting deps | Operates on a single-request `TaskDAG`, not a crew of dispatched work items |
| `AgenticLoop` (AD-545) | `cognitive/swe_harness/agentic_loop.py:47` | Multi-turn LLM↔tool executor (the AD-856 per-subtask executor) | — (reused as the per-subtask engine) |

**Net:** an agent today can complete *one* dispatched work item (AD-856), and a markdown plan can be fanned out (`ParallelDispatcher`), but there is no path that takes **one hard goal → crew fan-out → adversarial verify → converge → one synthesized completion** with attribution. That is the differentiator the market leaders are converging on (parallel subagents + adversarial verification), and ProbOS's wedge is doing it with **persistent, trusted, memory-bearing** crew instead of ephemeral subagents. This epic builds that loop **on top of** the existing dispatcher, not beside it (DRY — do NOT author a second dispatcher).

---

## AD-858 — LLM-driven semantic plan decomposer (single goal → sub-task DAG)

**Build.** A new `class LLMPlanDecomposer` implementing the existing `PlanDecomposer` Protocol (`consultation/dispatch.py:162`), in `src/probos/consultation/llm_decomposer.py`:
- Takes a single natural-language goal (the parent work item's title+description) and emits a `list[WorkItemSpec]` — sub-tasks with `depends_on` edges, suggested `agent`/`work_type`, and `resources` — using the tiered LLM client (`cognitive/llm_client.py`, **standard** tier; deep only if a config flag opts in).
- Output must be **schema-validated** before return: every `depends_on` references an emitted `spec_id` (no dangling edges), the graph is **acyclic** (reject + honest-degrade to a single-spec passthrough if the LLM emits a cycle), and spec count is bounded by a config cap (default 12 — Safety Budget; do not let the LLM fan out unbounded).
- It is a **drop-in** for `MarkdownPlanDecomposer`: `ParallelDispatcher(decomposer=LLMPlanDecomposer(...))`. Do NOT modify `ParallelDispatcher`'s dispatch logic — only provide a new decomposer. Conflict detection + serialization edges already run downstream and are reused unchanged.
- Config-gated (Pydantic in `config.py`): decomposer choice (`markdown`|`llm`, default `markdown`), max sub-tasks, tier. Default OFF so existing behavior is unchanged until opted in.

**Acceptance.** `tests/test_ad858_llm_decomposer.py` (≥6, fake LLM client returning canned JSON — NO real network): goal→multi-spec DAG with valid deps; dangling-dep edge rejected/repaired; cycle→honest-degrade to single passthrough spec; spec cap enforced; conforms to `PlanDecomposer` Protocol (structural); empty/garbage LLM output→single passthrough, not a crash. Verify Engineering-Principles compliance.

**Do NOT build:** the crew executor wiring (859), the verify gate (860), synthesis (861), UI. Do NOT modify `ParallelDispatcher` or `MarkdownPlanDecomposer`.

---

## AD-859 — Crew fan-out executor (each subtask runs the AD-856 AgenticLoop, results collected with provenance)

**Build.** Wire the dispatched sub-task `WorkItem`s to the AD-856 execution path and collect their results:
- A `class CrewTaskExecutor` in `src/probos/cognitive/crew_executor.py` that, given a parent work item already dispatched into child specs by `ParallelDispatcher`, drives the children: for each child whose `depends_on` is satisfied, dispatch it to its `assigned_to` agent via the existing `WorkItemRouter` path (`mesh/work_item_router.py:104`), which runs the **AD-856 AgenticLoop executor**. Respect the dependency DAG (a child only starts when its deps are `done`) — reuse the dispatcher's existing readiness semantics; do NOT re-implement topological scheduling.
- Collect each child's result into a `@dataclass SubtaskResult`: `work_item_id`, `spec_id`, `agent_id` (the **persistent** agent identity — durable provenance that ephemeral/session-scoped subagents cannot carry), `output`, `status`, `tool_trace_ref` (content-addressable ref to the AgenticLoop trace in `AttachmentStore`, NOT inline — AD-731 rule), `started_at`/`finished_at`.
- Bounded concurrency (config `max_parallel_subtasks`, default conservative) so a wide fan-out doesn't exhaust the LLM tier — mirror the `HttpFetchAgent` rate-limit philosophy, do NOT spawn unbounded tasks. Hold all task references (no fire-and-forget).
- New events: `CREW_TASK_STARTED`, `SUBTASK_COMPLETED` (append in `events.py` after the verified existing block; do NOT assume others exist).

**Acceptance.** `tests/test_ad859_crew_executor.py` (≥6, fake router/executor + real WorkItemStore): independent children run in parallel up to the cap; a child waits for its `depends_on` to be `done`; each `SubtaskResult` carries the persistent `agent_id` + a trace **ref** (not inline bytes); failed child surfaces status without aborting siblings; concurrency cap respected; events emitted. Verify Engineering-Principles compliance.

**Do NOT build:** the verify gate (860), synthesis (861), UI. Do NOT author a second dispatcher or a second AgenticLoop (reuse 856).

---

## AD-860 — Adversarial verification + convergence gate (the differentiator)

**Build.** The gate that makes results *trustworthy*, modeled on the `RedTeamAgent` **pattern** but for **semantic** task results (the existing `RedTeamAgent` only does deterministic tool re-execution — do NOT claim it covers this; this is new):
- A `class SubtaskVerifier` in `src/probos/cognitive/crew_verifier.py` that, for each `SubtaskResult`, runs an **independent** agent (a *different* crew member than the producer — independence is the point) to **refute** the result: an LLM-judge prompt that tries to find a flaw, missing requirement, or unsupported claim. Output: `@dataclass VerificationVerdict{ accepted: bool, confidence: float, critique: str, verifier_agent_id: str }`.
- **Convergence loop:** if a verdict is `accepted=False`, the subtask is re-dispatched (back through AD-859) with the critique appended to its context, up to a config `max_convergence_rounds` (default 2 — Safety Budget; do not loop unbounded). Converged = accepted, or max rounds reached (then escalate the subtask, do NOT silently accept a refuted result).
- **Reuse the consensus path for attribution, not a parallel one:** each verifier's verdict is recorded against the **trust ledger** (`TrustNetwork.record_outcome` — VERIFY the real signature before citing) so good verifiers and good producers both earn trust over runs (the persistent-crew wedge). Map verdicts onto `Vote`s so AD-861 can call `compute_shapley_values` — do NOT invent a new attribution scheme.
- Independence rule enforced: the verifier agent_id MUST differ from the producer agent_id; if no independent agent is available, honest-degrade to "unverified" status with a logged reason (do NOT let an agent verify itself).

**Acceptance.** `tests/test_ad860_crew_verifier.py` (≥7, fake LLM judge): accepted verdict folds through; refuted verdict triggers re-dispatch with critique; convergence stops at `max_convergence_rounds` then escalates (not silent-accept); verifier ≠ producer enforced; no-independent-agent→unverified degrade; verdicts recorded against trust ledger; verdicts map to `Vote` shape. Verify Engineering-Principles compliance.

**Do NOT build:** synthesis (861), UI. Do NOT modify `RedTeamAgent` (it stays the deterministic tool verifier; this is the semantic sibling).

---

## AD-861 — Result synthesis + Shapley attribution → parent completion

**Build.** Fold the verified subtask results into one parent completion:
- A `class CrewSynthesizer` in `src/probos/cognitive/crew_synth.py`: given the parent work item + its accepted `SubtaskResult`s, produce the parent's final output (LLM synthesis, standard tier) and transition the parent `WorkItem` to `done` via `update_work_item(..., status="done", metadata={...})`. Store the synthesis provenance (which subtasks + which verifiers contributed) as a content-addressable ref, NOT inline.
- **Attribution:** build `Vote`s from the producers + verifiers and call `compute_shapley_values(votes, approval_threshold, use_confidence_weights=True)` (`consensus/shapley.py:37`) to compute each crew member's marginal contribution; record the result against each agent's trust ledger and store an **episode** for the whole collaboration (every execution path stores an episode — copilot-instructions learning-loop rule; without it the crew never learns *which collaborators work well together*, which is the long-run Hebbian payoff that durable crew has over ephemeral subagents).
- New event `CREW_TASK_COMPLETED` carrying the parent id + attribution summary (append in `events.py`).

**Acceptance.** `tests/test_ad861_crew_synth.py` (≥6, real WorkItemStore + fake LLM): accepted subtasks synthesize into parent `done`; Shapley attribution sums correctly across producers+verifiers; episode stored for the collaboration; synthesis provenance is a **ref** not inline; partial (some subtasks failed) synthesizes from accepted-only with a recorded caveat; event emitted. Verify Engineering-Principles compliance.

**Do NOT build:** UI (862). Do NOT author a new attribution algorithm (reuse `compute_shapley_values`).

---

## AD-862 — HXI crew-collaboration surface (forward marker, dual-surface)

**Build (UI + thin API).** Per HXI Principles #4 (motion encodes state) and #6 (the canvas IS the information), surface the live collaboration so the Captain can watch fan-out → verify → converge without a command:
- `GET /api/crew-tasks/{parent_id}` returning the live tree (parent + subtasks + each subtask's status/verifier verdict/convergence round) — thin wrapper over the AD-859/860/861 state.
- HXI: a crew-collaboration view showing the parent and its fanned-out children, each child pulsing while running, flashing on verify, settling on converge (motion = state). Vitest component test required (UI-test rule — HXI has broken from untested UI changes before).

**Acceptance.** ≥3 API tests (happy/parent-not-found/in-progress) + ≥1 vitest component test. Verify Engineering-Principles compliance.

**Do NOT build:** changes to the decompose/execute/verify/synthesize logic.

---

## Build order & gates

`AD-858 → 859 → 860 → 861 → 862`, each: focused tests green → full gate → commit → **stop, review**. AD-859 (touches dispatch/runtime wiring) and AD-861 (touches the parent-completion path) get a corruption pre-check (`git diff --numstat`, PowerShell sort) before commit per the working-tree-integrity memory.

**Test invocation (CWD hazard):** `Set-Location -LiteralPath d:\ProbOS` then
`d:/ProbOS/.venv/Scripts/pytest.exe d:/ProbOS/tests/test_ad858_llm_decomposer.py --rootdir d:/ProbOS -q -n 0 -p no:cacheprovider`.

## Relationship to adjacent epics (do NOT duplicate)
- **AD-853–857 (Crew Self-Unblock)** is how a *single* agent gets unblocked mid-task (request a grant/skill/build). **This epic is how *multiple* agents complete *one hard task together*.** They compose: a subtask in AD-859 that hits a capability gap files an AD-854 `CapabilityRequest` and blocks/resumes via AD-855 — self-unblock is the per-subtask recovery path inside crew collaboration. Keep the boundary clean: 853–857 = capability acquisition; 858–862 = collaboration/verification/synthesis.
- **AD-856 (AgenticLoop executor)** is the per-subtask engine — this epic depends on it; build 856 first. Do NOT re-implement the loop.
- **`ParallelDispatcher` (AD-594c)** is the fan-out substrate — reused unchanged except for the swappable decomposer (858). Do NOT fork it.
- **`RedTeamAgent`** stays the *deterministic* tool verifier; AD-860 is the *semantic* sibling. Two verifiers, different jobs.

## Verify-first reminders for the Builder
- `TrustNetwork.record_outcome` signature is ASSUMED — grep the real method (per memory: real shape is `record_outcome(agent_id, success, weight, intent_type, source)`) before citing; do NOT invent `observe(...)`.
- `WorkItemRouter` dispatch entry point (`mesh/work_item_router.py:104`) — confirm the exact method name + params before wiring AD-859.
- `compute_shapley_values(votes, approval_threshold, use_confidence_weights)` takes `list[Vote]` — confirm the `Vote` dataclass fields before constructing them in AD-861.
- `update_work_item` / `create_work_item` signatures — confirm against `workforce.py` (the dispatcher calls `create_work_item(title, description, work_type, priority, depends_on, assigned_to, tags, metadata, created_by)`; mirror that shape).
- Only the events verified in `events.py` exist — add new event constants, do NOT assume others.
- Treat this spec as a lead, not ground truth: grep/read every cited API before editing (subagent/spec reports are leads — recurring memory lesson). The `ParallelDispatcher` already does fan-out + conflict serialization — read `consultation/dispatch.py:283-520` fully before adding anything, to avoid duplicating dispatch logic.
