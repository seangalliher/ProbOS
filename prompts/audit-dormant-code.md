# Architecture Audit — dormant code, drift, and duplication

**Use:** paste the "Instruction" section below into a new session, or say
*"run the audit in `prompts/audit-dormant-code.md`"*.

**Mode:** Architect. Read-only investigation. **Write no production code.** The
deliverable is a triaged candidate list, not fixes.

**Two halves, and the second is the expensive one.**

- **Part A (detectors 1-7)** finds code that *cannot run*. A dead branch costs
  confusion and nothing else.
- **Part B (detectors 8-11)** finds code that *runs but should not exist in the
  shape it has*: the same concept modelled twice, a design principle drifted
  away from, complexity carrying no corresponding value, a competitive claim
  that stopped being true. Every one of those taxes every future change.

Part A was written first because ten instances surfaced in one week. Part B was
added because the same week produced a subtler finding: **a thorough reader with
full repository access concluded that a live, armed, multi-agent execution
pipeline was dead code.** It was not. Four of that reader's five "inert" verdicts
were wrong. The subsystem was running and *unobservable* — which is a different
defect from being dormant, and a worse one, because nobody can even tell it needs
fixing.

---

## Why this audit exists

Between 2026-07-27 and 07-30, ten defects were found in ProbOS that share one
shape:

> **A mechanism was built, tested, and never actually connected to the thing that
> would exercise it. The suite was green the entire time.**

These were not found by tests. They were found by a human trying to use the
product. Each had been shipped for weeks or months.

### The ten, as ground truth for the detectors

| # | What was built | Why it never ran |
|---|---|---|
| AD-1157 | a `classification` field, validated | no caller ever supplied it — 2,453/2,453 records took the default |
| BF-688 | a `priority` parameter, honoured | all four sub-task handlers omitted it |
| BF-690 | a read-only action guard | the offered schema still advertised the refused actions, and the description told the agent to use them |
| BF-692 | `state()` element discovery | guarded on `hasattr(page, "list_elements")`; real Playwright has no such method, so it returned `[]` on every real page since AD-706 |
| BF-693 | `mouse_button(action="click")` | `hasattr(mouse, "click_button")` is always False, so every click landed at viewport (0,0) |
| BF-695 | the **entire** browser tool | `WindowsSelectorEventLoopPolicy` cannot spawn subprocesses; Playwright's driver never launched. Never ran inside `probos serve` on Windows, ever |
| AD-1162 | AD-1158's session binding | the context key was read but nothing in production wrote it |
| AD-1163 | the binding, now supplied | the **agent** was never told the session existed, so it never chose to use it |
| BF-697 | the agentic loop's `max_iterations` exit | set `stopped_reason` but never `final_text`, so a *successful* run reported nothing and a denial was sent instead — ~100K tokens of completed work discarded |
| AD-1165 | task promotion (still open) | `WorkItemAgenticExecutor` is the *task* executor; the DM path calls it inline inside a 60s TTL and never creates a work item |

### The two root causes

1. **The test double was more capable than production.** A fake `page`
   implementing `list_elements`. A `Mouse` stub implementing `click_button`. A
   test supplying the very context key it existed to prove arrived from
   elsewhere. Scripted `content_blocks`. In each case the suite exercised a
   capability the real object does not have.
2. **The suite ran a different configuration than production.** `asyncio_mode =
   "auto"` puts tests on `ProactorEventLoop`; `__main__.py:2456` puts production
   on `WindowsSelectorEventLoopPolicy`. Opposite loops. A whole bug class was
   structurally invisible.

### The forcing question

> **Name the real caller. Not the test — the production path.**

Four of the ten die on that immediately. AD-1163 is the instructive exception:
producer *and* reader were both wired and both correct, and the agent who had to
*decide* to invoke the capability was never told it existed. So the question has
a second half:

> **For anything an agent elects to use, can the agent know it is there?**

---

## Instruction (paste this)

Run a read-only dormant-code audit of `d:\ProbOS`. Context and rationale are in
`prompts/audit-dormant-code.md` — read it first.

Run each detector below as a **separate read-only Explore subagent**, so one
sweep's noise does not contaminate another. Do not write production code. Do not
fix anything you find. The deliverable is a triaged candidate list.

### Detector 1 — test doubles more capable than the real object (HIGHEST YIELD)

Accounts for 4 of the 10. For every fake/stub/mock class under `tests/`, identify
the real class it stands in for, and report any method or attribute the double
implements that the real class does not.

Highest-value targets: doubles for third-party objects (Playwright `Page`,
`Mouse`, `Browser`; chromadb collections; httpx clients; NATS), because the real
API cannot be checked by the type system here.

Report: double, real class, the extra members, and every production call site
guarded by `hasattr()` on one of them. **A `hasattr()` guard against a method
only the double has is a confirmed dormant path, not a candidate.**

### Detector 2 — reads with no writer

Accounts for 3 of the 10. For every `context["key"]`, `.get("key")`,
`params.get("key")` and equivalent read of a string-keyed value, search for a
production writer of that key. Exclude test files from the writer search — a key
written only by tests is exactly the defect.

Report: the key, the read site, and whether a production writer exists.

### Detector 3 — test/production environment divergence

Found BF-695. Enumerate everything conditioned on `sys.platform`, event-loop
type, `os.environ`, or a config flag where the test environment and production
differ. Start from `pyproject.toml`'s pytest config, `tests/conftest.py`, and
`__main__.py`.

Report each divergence and what production behaviour it renders untested.

### Detector 4 — log signatures with zero live hits

For each feature shipping a distinctive log marker (`AD-NNN:` / `BF-NNN:`), grep
the Captain's live log at `%LOCALAPPDATA%\ProbOS\data\logs\probos.log`. Zero hits
for a marker that should fire routinely = suspect inert.

**Caveat that cost three dead ends:** absence of evidence is not evidence of
absence *if the event is never recorded*. Before concluding a feature is dormant,
confirm its marker is actually emitted on the path in question. `agentic_tool_call_*`
events are never persisted to `events.db` — that artifact produced a false "no
agent has ever made a tool call" conclusion. Cross-check with a second signal
(token arithmetic, a persisted trace, a DB row) before reporting.

### Detector 5 — declared-but-never-persisted events

Enumerate `EventType` members and check for corresponding rows in the live
`events.db`. Zero rows for an event that should fire = either dormant code or a
persistence gap. Both matter; distinguish them.

### Detector 6 — default-OFF flags never enabled

Diff shipped config defaults against the Captain's local `config/system.yaml`
(skip-worktree — read it, never stage it). Report every default-OFF feature never
switched on. Precedent: the entire Σ epic sat dormant on the live instance until
the Captain asked.

### Detector 7 — public methods with no production caller

Public methods whose only call sites are tests. Weakest detector — extension
points are legitimately uncalled — so run it last and expect heavy triage.

---

# Part B — is the architecture still the one we meant to build?

Part A asks "can this run?" Part B asks **"should this exist, in this shape, at
all?"** Run these as separate subagents too. They produce fewer findings than
Part A and each one is worth more.

The governing question:

> **If we were starting today, knowing what we know, would we build it this way?
> If not, what specifically caused the drift, and what does keeping it cost?**

### Detector 8 — the same concept modelled twice (HIGHEST YIELD IN PART B)

ProbOS accreted its work-management vocabulary over ~700 ADs. Enumerate every
durable container for *work*, *conversation*, *grouping*, and *state*, and report
which pairs overlap.

Known candidates to start from, **not** an exhaustive list — find the ones nobody
has noticed:

| Concept | Containers that model it |
|---|---|
| a unit of work | `WorkItem`, `CrewSessionContract`, `WorkItem.steps`, `SubtaskResult`, `AgentTask`, `PersistentTask` |
| a grouping of work | `Project`, `ChatThread.project_id`, `WorkItem.parent_id`, board groups |
| a place work happens | `ChatThread`, task room, crew session room, workspace, `workspace_root` |
| a checklist | `WorkItem.steps`, `[TODOS]` reply tags, the HXI TodosList |
| an authorization | `ToolPermissionStore`, `IntentGrantStore`, `DepartmentToolGrantStore`, `ActionApprovalStore`, `WorkPermitStore`, `CaptainOrder` |
| a scheduled thing | `duty_schedule`, `WatchManager` standing tasks, cron-ish proactive loop, `WorkItem.schedule` |

For each overlapping pair report: **do they share a source of truth, or can they
disagree?** Two containers that can disagree about the same fact is the defect.
Two that project the same fact differently for different audiences is fine — say
which it is.

Also report **orphan containers**: a model with a store, an API and no reader, or
a reader with no writer that Part A missed because both halves exist but are
never connected end to end.

### Detector 9 — drift from the stated design principles

`.github/copilot-instructions.md` carries twelve numbered design principles and
eleven HXI principles. `Vibes/Nooplex_Final.md` carries the theoretical model
(`M = ⟨A, Σ, K, E, Φ, Ω, Ψ⟩`) and the three governance axioms (Safety Budget,
Reversibility Preference, Minimal Authority).

For each principle, find the **strongest counter-example in the current tree** and
rate it: *upheld* / *partially drifted* / *contradicted*. Cite the file and line.

Be adversarial. "Every component is an autonomous agent" and "no central
scheduler" are strong claims — look for the central scheduler. "Instructions-first
CognitiveAgent" is a strong claim — look for reasoning hardcoded in `decide()`.
Do not accept a principle as upheld because the docstring says so.

Report separately: principles that are **aspirational and should be restated**
versus principles that are **real and being violated**. Those need opposite
responses, and conflating them is how a principles list becomes decoration.

### Detector 10 — complexity with no corresponding value

For each subsystem over roughly 500 lines, or each config section over roughly
ten flags, answer three questions:

1. **What does the Captain get that they would not get without it?** State it as
   an observable behaviour, not a capability noun.
2. **Has it ever produced that behaviour on the live instance?** Use the Part A
   detector-4 log evidence, and honour its caveat: absence of a marker is not
   absence of the behaviour if the marker is never emitted.
3. **What would deleting it cost?**

Flag anything where (1) is hard to state, (2) is "no", and (3) is "little". Also
flag **flag proliferation**: a config section whose flags are never varied
independently is one flag wearing several hats.

This detector is the one most likely to produce an uncomfortable answer about
work the same author shipped last week. Report it anyway.

### Detector 11 — competitive claims that expired

**Never answer this from training data.** Model training cutoffs are months to
years behind, this field moves weekly, and a stale competitive claim is worse
than no claim because it justifies not building something.

**Fetch current data** for each named comparator — GitHub repository pages for
stars, last-commit date and README; the vendor's own current documentation for
feature sets. Record the fetch date next to every claim.

Comparators as of 2026-07: GitHub Copilot, Claude Code, OpenAI Codex, OpenClaw
(`openclaw/openclaw`), Hermes Agent (`NousResearch/hermes-agent`), plus whatever
has appeared since — search rather than assuming the list is complete.

Then take every competitive claim in `docs/`, `README.md`, the commercial
`research/` and `docs/commercial-roadmap.md`, and mark it **still true** /
**newly false** / **unverifiable**. A claim of the form "only ProbOS does X" is
the highest-risk shape; check those first.

Worked example of why this matters: in July 2026 the standing internal claim was
that the coding harnesses are "single-agent, single-session, ephemeral, with no
inter-agent messaging or persistent per-agent memory." A thirty-second fetch of
the current Claude Code documentation showed agent teams, inter-agent
`SendMessage`, a sibling roster, per-subagent persistent memory scoped to
user/project/local, `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` tools, cron
tools, spawn-depth limits and concurrency limits. **The claim had gone stale and
was being used to justify a differentiation argument that needed narrowing.**
Find the next one of those.

---

## Output

Write the report to **`prompts/audit-findings-YYYY-MM-DD.md`** (today's date).
Leave it **untracked** — same handling as BF prompts. Do not put it under
`docs/development/`: that is public OSS documentation, and a catalogue of dormant
subsystems reads as a flaw inventory rather than product docs.

Also print a summary to the chat, but the file is the artifact — a run produces
more findings than fit usefully in a response, and dating it lets a later run be
diffed against this one.

One section per detector. Every finding cited `path/file.py:LINE`. For each
candidate give a **confidence**:

- **CONFIRMED** — the mechanism provably cannot run in production (e.g. a
  `hasattr()` guard on a method the real object lacks). For Part B: the
  duplication or drift is demonstrable from the code, not inferred.
- **LIKELY** — strong signal, needs one check to settle.
- **CANDIDATE** — worth a look, expect false positives.

Finish with **two** tables, not one:

1. **Part A**, ordered by *user impact if dormant* — not by detector.
2. **Part B**, ordered by *cost of keeping it* — how much every future change
   pays for the duplication, drift or complexity. A subsystem nobody touches is
   cheap to leave wrong; one in the path of the next three ADs is not.

### The file is evidence; issues are work

**After writing the report, automatically create a GitHub issue for every
CONFIRMED finding.** Leave LIKELY and CANDIDATE in the file only — a markdown
checklist of thirty items becomes a parallel backlog that drifts from the issues.
Only promote what is settled.

**Part A findings are BF issues. Part B findings are not.** A duplicated
subsystem is not a bug; it is a design decision that needs making, and filing it
as `BF-NNN: <symptom>` misrepresents it and invites someone to "fix" it with a
patch. File Part B CONFIRMED findings as **`AD-NNN: <the decision to be made>`**
with the `enhancement` label, and state the options rather than prescribing one.
If a Part B finding needs the Captain's judgement about product direction — which
most consolidation decisions do — say so in the issue body instead of choosing.

Mint AD numbers under the same three-source ceiling rule as BF numbers below.

#### Procedure — follow exactly; each step exists because it has failed before

1. **Establish the BF ceiling from three sources, not one.** `DECISIONS.md`,
   `PROGRESS.md`, **and the uncommitted working tree** — tracked *and* untracked.
   The tracker lags in-flight work: BF-674 was once minted for a fix while an
   untracked `test_bf674_*.py` had already claimed it. Run
   `git status --short` plus a recursive filename/content scan for `BF-\d+`.
   State the ceiling explicitly before assigning anything.

2. **Search for duplicates first.**
   `gh issue list -R seangalliher/ProbOS --state all --limit 100 --search "<keyword>"`.
   A dormant subsystem may already have an open issue. Skip and note it rather
   than filing a second.

3. **Author each body with the `create_file` tool**, never by string-building in
   PowerShell. A gh body round-tripped through the console collapses to one line
   and mojibakes every non-ASCII character.

4. **Verify the body file exists and is non-empty immediately before use.**
   Referencing a deleted or empty temp file makes `gh` set the issue body to two
   bytes **and still report success**. Check `Test-Path` and `(Get-Item $f).Length`.

5. `gh issue create -R seangalliher/ProbOS --title "BF-NNN: <symptom>" --body-file <f> --label bug`

6. **Verify creation before retrying.** `gh issue create` in a multi-line block
   can succeed while printing nothing. Confirm with
   `gh issue list --search "BF-NNN in:title"` before assuming failure — this is
   how issues get double-created.

7. **Report the created issue numbers and URLs**, and update the report file with
   each finding's issue number so the file and the tracker stay reconciled.

#### Issue body shape

Follow house style: `## Problem` (the symptom a user would notice, not the code
smell) · `## Evidence` (`file:LINE`, and *why it provably cannot run*) · `## Why
no test caught it` (name the double or the environment divergence) · `##
Acceptance`. State plainly if the fix direction is uncertain — a wrong prescribed
fix is worse than an honest "needs design".

#### Do not file

Legitimately-uncalled extension points, commercial-overlay seams, and
deliberately-dormant flagged features. If a finding is CONFIRMED-dormant but
*intentionally* so, record it in the report with that reasoning and file nothing.

## Expect false positives, and say so

Legitimate causes that are **not** defects: deliberately-dormant features awaiting
a flag; extension points with no consumer yet (`HookBus.ask` is a known one);
commercial-overlay seams; forward-compatibility shims. Triage is the real work —
a list of thirty candidates where five are real is a good outcome.

Part B has its own false-positive class: **two containers that project the same
fact for different audiences are not duplication.** A board card and a chat room
both showing a task's state is correct design. The defect is only when they can
*disagree* — separate writes, separate sources of truth, no reconciliation. Apply
that test before reporting.

## Verify before you report a subsystem dead

This rule was added because a thorough survey with full repository access
reported five subsystems inert and **four of the five verdicts were wrong**. It
concluded no production caller wrote work items (there were six), that the board
was local React state (it POSTs transition/assign/create through the store), and
that crew orchestration was off (`orchestrator_enabled` was `True` on the live
instance).

Before reporting anything dormant, run all three of these and show the result:

1. `grep` for the **writer**, not only the reader, across `src/` with tests
   excluded — and check UI state modules, not just components, because mutations
   often live in the store rather than at the call site.
2. Load the **Captain's live config** through the real `SystemConfig` and print
   the actual flag value. Shipped default ≠ live value; that is the entire point
   of detector 6.
3. Name the **ingress**: the endpoint, event, intent or loop that starts it.

A subsystem that is running but invisible is a different finding from a dormant
one, and it belongs in Part B under detector 10, not Part A.

## Do NOT

- Do not fix anything. Findings only.
- Do not modify tests to "prove" a finding.
- Do not stage or edit `config/system.yaml` (skip-worktree `S`).
- Do not run the full suite; this audit needs no test run.
- Do not answer detector 11 from training data. **Fetch.** A stale competitive
  claim is worse than no claim, because it is used to justify not building
  something. Record the fetch date beside every comparator finding.
- Do not consolidate anything Part B surfaces. Merging two containers is a
  product decision with migration cost, and this audit's job is to make the
  decision *visible*, not to make it.
- Do not theorise past the evidence. This week produced four wrong inferences from
  reasoning ahead of the data — including a confident "no agent has ever made a
  tool call" that was contradicted by token arithmetic already in the log. When a
  probe would settle a question in thirty seconds, run the probe.
