# BF-961 (#1774): The todo and scheduler agents refuse an intent whose stored list could not be read, so a failed or refused read no longer replaces the stored list

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was unavailable), 2026-11-08
**Status:** ready to build on `origin/main` `6ee2bfa0` (reading tree `D:\ProbOS-worktrees\bf944-base`). **Oracle:** no test run (a read-only consult). An in-memory script applied the 13 pairs and the 2 new files to the LF blobs (each SEARCH once, every result parses), exec'd the patched modules over the real tree and drove the agents by hand, with no pytest (section 11): on the base the 17 class cases fail at their own `assert` and 9 hold; on M2's head all 26 hold; the ten mutants of section 9 fail the cases listed there.
**Base blobs (`6ee2bfa0`):** `productivity_agents.py` `90dde75d6894638268d30ae7b07f9bbe7d6ad0f2`, `organizer_agents.py` `228ec27e082abdc8423124a074434d40dd1f61d9`, `file_reader.py` `539a39766625c70f67a8bd19a9541445164bd83f`, `PROGRESS.md` `eea8115a0527391ac72a45fbed913975478a2daf`, `DECISIONS.md` `b90240f78bafda55a9c4db4cdb71f5ba92518bd5`.
**Orchestrator oracle and amendments (2026-11-08):** the build tree is `origin/main` `50caed13` (BF-945's merge, on `6ee2bfa0`): `PROGRESS.md`, `DECISIONS.md` and the two ledger files differ from `6ee2bfa0` by BF-945's text; the three code blobs above are unchanged, so the header check applies to them. Every block (the twelve pairs of M2, the marker pair, the two tracker pairs and the two new files) was applied by tool on `6ee2bfa0` and again on `50caed13`, each SEARCH matching exactly once. On `6ee2bfa0`: G1 gave 9 passed and 17 xfailed (with `--runxfail` 17 failed, at `result.success is False`), G2 gave 693 passed and 2 skipped, the ledger generator, the architecture check and the ledger test (33 passed) were clean, and a census of section 9's ten rows killed all ten (baseline 26 passed). **One amendment:** P3-2 appends after BF-945's entry, which is the last in `DECISIONS.md` on `50caed13`, so that the file stays in the order the changes landed; its SEARCH is BF-945's last bullet, which occurs once.
**Amendment A1 (2026-11-09, after review round 1 by `gpt-6.1-sol`):** the review found one code regression and two statements that said more than the evidence, all closed by the commit `BF-961 A1`. (1) `read_stored_list` unwrapped a dictionary result before testing it for emptiness, where `_mesh_read_file` tested the raw result first, so four answers that only a double or a federated peer gives (`{}`, `{"content": False}`, `{"content": None}`, and a dictionary with empty `content` before a later success) were shown differently from before, against the claim in section 12 that a success's text is returned as `_mesh_read_file` returned it. The loop now tests the raw result and unwraps only a truthy one (the docstring and the `FOUND` comment say so). A new test T7 (10 cases) and five more rows of T5 pin those four answers and a success beside a failure for the todo, scheduler and note agents: on the source before the repair 12 of the 15 new cases fail, and on `50caed13` all 15 pass. An orchestrator probe over 28 answer shapes (outside the repository) compared the old read with the new one: before the repair 19 equal, 4 intended refusals and 5 different; after it 24 equal, 4 refusals and 0 different. (2) L5 and D3's row 1 said no write depends on the note read; a requested `read` followed by a model answer that says `save` does write (run on `6ee2bfa0` and on `d9b2a9da`), so L5, D3's row 1, the comment in `organizer_agents.py` and DECISIONS G3 now say what the code does; that the requested action is not checked at the write is a base defect left to a follow-up. (3) DECISIONS G1 left out the successful-read exception, D5's "each answer shape" said more than the cases run, and L7 gave only the inner 60 s bound; they now say what the cases run, and L7 adds the DAG node's 10 s timeout. L9 records what the old read did with an empty result that is not a string. Section 9 gains rows 11 to 13, for A1's head: a census of all 13 rows on A1's source and tests killed all 13 (the 41-case file alone; baseline 41 passed). The blocks of section 7 stay as the record of M1 to M3; the lines the A1 pairs replace are superseded in the tree. Sections 4 and 6 count the file as M1 to M3 built it (26 cases, T1 to T6); the final file has 41 (T5 7, T7 10), of which 24 pass on the unfixed tree and 17 fail.
**Amendment A2 (2026-11-09, after review round 2 by `gpt-6.1-sol`):** the review confirmed F1 to F3 resolved and found one statement that said more than the evidence: the comment on `_AS_ALWAYS` in the test file said the old read returned `""` for `{}`, where it returned `None`. Run on `50caed13` (the function extracted by AST, outside the repository): `{}`, `[]`, `0`, `False`, `b""` and a real reader's empty string each returned `None`; `{"content": False}` returned `'False'`, `{"content": None}` returned `'None'`, a dictionary with empty `content` before a later text returned `''`, and a failure before a text returned the text. The comment now says what each agent shows and, for the two shapes it shows as empty, what the old read returned (`None` and `''`); L9 says what the old read returned and where the write is pinned. Both are corrected in the commit `BF-961 A2`; no code changes.
**Dependencies:** none; sequenced before BF-944 (#1717). **Tier:** M1 STANDARD (tests); M2 HIGH (a data-integrity guard; edits the reader's module); M3 STANDARD. **Estimated tests:** one new file, 26 cases (9 pass, 17 xfail at M1). **BF number:** BF-961, held by #1774; nothing new is allocated (section 11).

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` for the five paths prints the blobs above, `git diff --stat 6ee2bfa0 HEAD -- src/probos/agents src/probos/mesh PROGRESS.md DECISIONS.md` is empty, and neither new file exists. If one fails, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The read.** `TodoAgent.perceive` (`productivity_agents.py:164-174`) and `SchedulerAgent.perceive` (`organizer_agents.py:251-281`) call `_mesh_read_file` (`productivity_agents.py:101-113`; a copy at `organizer_agents.py:42-54`, AST-identical but for a docstring). It broadcasts `read_file` and returns the first answer with `success` and a truthy `result`, else `None`. Each agent shows the model `None` as `[]`.
2. **The write.** `act` (`productivity_agents.py:176-197`, `organizer_agents.py:283-359`) runs `json.loads` on the model's output; for a JSON object with `todos` (`reminders`) it writes `json.dumps` of that list through `_mesh_write_file` to `FileWriterAgent.commit_write` (`file_writer.py:146-164`: `mkdir`, then `p.write_text`; no backup, no check of the read), and answers `Failed to save todos` (`reminders`) when that fails (`:193`, `:354`). The scheduler's `remind` first creates a task (`organizer_agents.py:306`, `:314`); `list` and a `cancel` that names a task on a runtime with a scheduler return before the write (`:322`, `:339`).
3. **Reach.** Each bundled pool has two agents built with the runtime (`agent_fleet.py:109-111`, `:117`; registered `runtime.py:1618-1620`); the file pool has three readers and is built without it (`:47`, `:57`). A failed intent reaches the user as `error=<text>` in the reflect prompt (`decomposer.py:476`, `:759`, `:764`), as `Failed to save todos` does.
4. **The defect.** An answer that is neither a file's text nor "no such file", or no answer, reads as an empty list, and the list the model builds from it replaces the stored one. BF-944 makes that ordinary for an operator who sets `read_roots` without `~/.probos`.

What one broadcast can return and what each consumer does with it (answer texts measured on the real reader, section 11):

| # | Answer(s) (producer) | Today, all three agents | After M2: status | After M2: todo and scheduler | After M2: note agent |
|---|---|---|---|---|---|
| 1 | a success with text (`file_reader.py:141-146`) | the text | FOUND | text shown; the model's list written | note shown |
| 2 | a success with `""`, an existing empty file | `[]` shown | FOUND, empty | `[]` shown | `not found` |
| 3 | every answer `File not found: <path>` (`:136`) | `[]` shown | MISSING | `[]` shown; the first save creates the file | `not found` |
| 4 | a failure with the policy's text (`:132-133`; `path is outside every readable root`) | `[]` shown; the model's list written over the file (the defect) | FAILED | refused: no model request, no `commit_write`, `success` False | `not found`, WARNING |
| 5 | a failure with another text: an OS error (`:147-148`), `Not a file: <path>` (`:138`), a handler's `str(e)` (`intent.py:1901-1906`) | as row 4 | FAILED | as row 4 | as row 4 |
| 6 | no answer: `[]` (closed bus `intent.py:1355`, pre-intent denial `:1368`, no candidate, an answer after the 60 s TTL `:1467-1477`) | as row 4 | FAILED | as row 4 | as row 4 |
| 7 | a success with `result` None; a runtime without `intent_bus` | as row 4 | FAILED | as row 4 | as row 4 |
| 8 | a success with text beside failures | the text | FOUND | as row 1 | as row 1 |
| 9 | not-found beside another failure, no success | as row 4 | FAILED | as row 4 | as row 4 |

## 2. Solution

New `agents/utility/stored_list.py`: `read_stored_list(runtime, path) -> ListRead(status, text, reason)` and the mixin `UnreadableListGuard`. `agents/file_reader.py` gains `FILE_NOT_FOUND_MARK` and `is_file_not_found` and builds its two not-found answers from the mark (text unchanged). `TodoAgent` and `SchedulerAgent` take the mixin; their `perceive` reads through `self._stored_list`, which on a failed read sets the observation's refusal text and returns None; the mixin's `decide` then returns the error decision before the model, and the first line of each `act` (`:177`, `:284`) answers `success` False. `_mesh_read_file` is deleted from both modules; the note agent reads through `read_stored_list(...).text`, its text unchanged for every row. `commit_write` and both `_mesh_write_file` are untouched.

## 3. Decisions

**D1. How the read says which it was** (Law of Demeter, DRY, fail closed).

| # | Option | Judgement |
|---|---|---|
| 1 | The reader owns the mark of its not-found answer (`FILE_NOT_FOUND_MARK`, `is_file_not_found`); one helper classifies the broadcast into a frozen `ListRead(status, text, reason)`: FOUND (empty included), MISSING (every answer not-found), FAILED (all else) (chosen) | No result shape changes and any answer with the reader's text reads alike; an unrecognised answer fails closed; T4 runs the real reader (an answer not built from the mark fails it) and T6 pins the text. Text, not a field, because the reader sets no structured one (measured); the idiom is `tools/protocol.py:97-114` |
| 2 | A structured field in `IntentResult.metadata`, set by the reader | The sound end state, but a change to the shared reader's results, the text is still needed for older peers, and the wire may drop `metadata` (`IntentBus._reply_bytes`) |
| 3 | The agent stats the path itself after a failed read | A second source of truth beside the read policy BF-944 applies, and a local answer to a broadcast a peer may have answered |
| 4 | `stat_file`; or `str \| None`; or a raise | `stat_file` answers `File not found: <path>` or the refusal text, as `read_file` does (measured); `None` for three things is this defect; a raise through `perceive` leaves `decide` no way to answer |

**D2. What each agent does when the read failed** (BF-769/BF-772's gate; Fail Fast; DRY).

| # | Option | Judgement |
|---|---|---|
| 1 | `perceive` marks the observation; one shared `decide` returns `{"action": "error", "reason": <text>}` (a shape `decide` already returns, `cognitive_agent.py:3743`) before the model; each existing `act` answers `success` False; text `Could not read <your todo list or your saved reminders>; nothing was changed or saved.`; one mixin in a new module both agents import (chosen) | The shape of `web_agents._FetchGatedMixin` (`:288-388`); the model never sees a list it could build over, and the decision cache and procedural memory are not consulted; no `act` edit |
| 2 | Run the model; `act` refuses only the file write | Needs the failure carried on the decision; the model answers about a list it was not shown; the scheduler's `remind` would create its task and say nothing of the file |
| 3 | Tell the model the list is unavailable | The instructions tell it to maintain the list (`productivity_agents.py:133-145`); a model's compliance is not a guard |
| 4 | Two copies kept in step, one per module | The modules already hold identical copies of both helpers; a third pair is how the defect came to be in two agents |

**D3. The note agent.**

| # | Option | Judgement |
|---|---|---|
| 1 | Its read goes through `read_stored_list(...).text`, its text unchanged for every row; the gap is a recorded limit, L5 (chosen) | No code writes what its read returned: a wrong sentence, not a loss by that path (L5 says what the model's own answer can still do). The status-discarding helper is deleted from both modules, as BF-772 deleted `_mesh_fetch` |
| 2 | Also refuse a failed note read | Cheap with the mixin, but another defect class (honesty) and a changed text for an agent no issue names |
| 3 | Keep `_mesh_read_file` in `organizer_agents.py` for it | A lossy helper and a second broadcast loop kept for one caller |

**D4. The write itself.**

| # | Option | Judgement |
|---|---|---|
| 1 | Leave `commit_write` and both `_mesh_write_file` (chosen) | The defect is the read. The writer is shared with `submit_write_with_consensus`; BF-911's inventory names both helpers by scope (`test_bf911_protected_config_write_refusal.py:960-961`); AD-1346's file-write census names `file_writer.py` (`ad1346_file_write_census.py:164`) |
| 2 | A `.bak` copy in the bundled agents before they replace the file | Would also cover a model that returns a shorter list; new files in `~/.probos` and a new behaviour: a follow-up |
| 3 | Write a temp file and `os.replace` in `commit_write` | Covers a crash mid-write; changes every consensus write, adds a flagged primitive to `file_writer.py`, and a replace over an open file can fail on Windows |

BF-961 does not promise a file that reads but is not a valid list, a crash during `write_text`, or a good list from the model (L2).

**D5. Tests.** The real agents' `handle_intent` against a runtime double (twelve answer shapes: found, missing, refused, os-error, mixed, no-content, nobody, four dictionary results and a success beside a failure; a runtime without `intent_bus` is the helper's first return and no case runs it), a counting model double, `commit_write` recorded, `~` moved, a control round per premise, and the three real readers behind the bus for the seam (chosen): one test crosses file, reader, helper, agent and write. Rejected: tests of `read_stored_list` alone (no seam); a source-text test (it cannot tell a required line from the shipped one).

**D6. Trackers and BF-944's text.** PROGRESS.md, DECISIONS.md and the ledger (M3), as BF-945's; the roadmap is not edited (`git grep BF-961` finds only the generated next-free row `docs/development/open-ads-report.md:32`), and no document under `docs/` names the two files (section 11). BF-944's contract (not built) must change when re-anchored: L4.

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-13, then N2-1 (removing the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf961_unreadable_stored_list.py -q -n 0 -p no:randomly`. **Expected: 9 passed** (T4 to T6), **17 xfailed** (T1 to T3). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `PY -m pytest tests/test_bf961_unreadable_stored_list.py tests/test_utility_agents.py tests/test_task_scheduler.py tests/test_ad686_oracle_semantic_tier.py tests/test_ad1344_constitution_write_refusal.py tests/test_bf911_protected_config_write_refusal.py tests/test_distribution.py::TestUtilityRuntimeIntegration tests/test_file_reader.py tests/test_bf758_file_read_confinement.py tests/test_bf908_floor_and_children.py tests/test_cognitive_agent.py tests/test_consensus_integration.py tests/test_ad152_regressions.py tests/test_ad983a_capability_affordances.py tests/test_ad1026_boot_verbosity.py tests/test_agent_tiers.py tests/test_prompt_builder.py tests/test_workflow_cache.py tests/test_layer_boundaries.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_egress_census.py -q -n 0 -p no:randomly` (the new file; the files naming the agents or helpers; the 11 files naming `FileReaderAgent`; the layer test; the AD-1346 scans: section 11). (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file 26 passed; every other file 0 failed and collected counts equal M0; the check clean.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-961 M1: tests for a failed read of the todo and scheduler agents' stored list never leading to a write, xfail until built (#1774)`
- **M2:** `BF-961 M2: the todo and scheduler agents refuse an intent whose stored list could not be read, before the model and any write (#1774)`
- **M3:** `BF-961 M3: trackers and ledger (#1774)`; its body ends with the line `Closes #1774.`

## 6. Tests (`tests/test_bf961_unreadable_stored_list.py`)

| Id | Cases | Covers (function) | xfail until |
|---|---|---|---|
| T1 | 10 | Class: a failed read (refused, OS error, not-found beside another failure, a success with no content, nobody answers) x both agents: the refusal text, no model request, no `commit_write`, the stored bytes unchanged; a control round first (`test_the_intent_is_refused_before_the_model_and_nothing_is_written`) | M2 |
| T2 | 6 | Class: the refusal through the three real readers built with a runtime whose `read_roots` omit `~/.probos` (BF-944's case), file stored, missing or empty, x both agents (`test_a_read_the_policy_refuses_writes_nothing`) | M2 |
| T3 | 1 | Class: both agents' `decide` is the one guard (`test_the_guard_is_not_shadowed`) | M2 |
| T4 | 6 | Seam: the three real readers, file stored, missing or empty, x both agents: the model is shown the list or `[]`, the write lands (`test_through_the_real_readers_a_stored_missing_or_empty_file_still_works`) | none |
| T5 | 2 | The note agent's read: a note is shown, a missing one reads `not found` (`test_the_note_agent_reads_as_before`) | none |
| T6 | 1 | The reader's `File not found: <path>` for `read_file` and `stat_file` (`test_the_reader_still_says_file_not_found_in_its_own_words`) | none |

**How each xfail case fails on the base.** T1 and T2 at `assert result.success is False and result.error == ...`: on the base the model runs and its list is written, so `success` is True; the control round before it passes. The assertions after the first first run at G2. T3 at its one `assert` (both `decide` are `CognitiveAgent.decide`).

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf961_unreadable_stored_list.py`:

```python
"""BF-961 (#1774): a failed or refused read of a bundled agent's stored list never leads to a write.

The real TodoAgent and SchedulerAgent run ``handle_intent`` against a runtime double whose ``intent_bus.broadcast``
returns the answer under test (the seam cases: the three real FileReaderAgent), with ~ moved under ``tmp_path`` and
``commit_write`` recorded. The doubles are the runtime with its bus, and the model; no network. The class holds the cases the unfixed tree fails; the
functions before it pass on both. No BF-961 name is imported.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility.organizer_agents import NoteTakerAgent, SchedulerAgent
from probos.agents.utility.productivity_agents import TodoAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentMessage, IntentResult, LLMRequest, LLMResponse, Priority

NEW = {"text": "new item"}
STORED = json.dumps([{"text": "stored item"}])
KINDS = {  # agent, intent, file, the key its model answer carries the list under, what the model is shown
    "todo": SimpleNamespace(cls=TodoAgent, intent="manage_todo", file="todos.json", key="todos", label="Current todos", what="your todo list"),
    "scheduler": SimpleNamespace(cls=SchedulerAgent, intent="manage_schedule", file="reminders.json", key="reminders", label="Saved reminders", what="your saved reminders"),
}
STATES = {"stored": STORED, "missing": None, "empty": ""}  # what the agent's file holds; None: no file
_ANSWERS = {  # one read_file broadcast: (success, result, error) per answer
    "found": [(True, STORED, None)] * 3,
    "missing": [(False, None, "File not found: x")] * 3,
    "refused": [(False, None, "path is outside every readable root")] * 3,
    "os-error": [(False, None, "[Errno 13] Permission denied: 'x'")],
    "mixed": [(False, None, "File not found: x"), (False, None, "handler failed")],
    "no-content": [(True, None, None)],
    "nobody": [],
}


class _Bus:
    def __init__(self, shape: str) -> None:
        self.shape = shape

    async def broadcast(self, intent: IntentMessage, *args: object, **kwargs: object) -> list[IntentResult]:
        return [IntentResult(intent_id=intent.id, agent_id="reader", success=s, result=r, error=e) for s, r, e in _ANSWERS[self.shape]]


class _Readers:
    """The three real FileReaderAgents of the filesystem pool behind a bus; *runtime* is what BF-944 will hand them."""

    def __init__(self, runtime: object = None) -> None:
        self.agents = [FileReaderAgent(agent_id=f"fr-{i}", runtime=runtime) for i in range(3)]

    async def broadcast(self, intent: IntentMessage, *args: object, **kwargs: object) -> list[IntentResult]:
        answers = [await agent.handle_intent(intent) for agent in self.agents]
        return [answer for answer in answers if answer is not None]


class _Model(MockLLMClient):
    """Answers every request with one text and keeps the requests."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self.text, model="mock", tier=request.tier, tokens_used=1, cached=False, request_id=request.id)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """~ moved under tmp_path; ``writes`` lists the path of every commit_write call (each is passed on)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    writes: list[str] = []
    real = FileWriterAgent.commit_write

    async def record(path: str, content: str, *, runtime: object = None) -> dict:
        writes.append(path)
        return await real(path, content, runtime=runtime)

    monkeypatch.setattr(FileWriterAgent, "commit_write", staticmethod(record))
    return SimpleNamespace(home=home, tmp=tmp_path, writes=writes)


def _confining(tmp_path: Path) -> SimpleNamespace:
    """A runtime whose read policy admits an unrelated directory and a workspace root, so ~/.probos is outside every readable root."""
    data, allowed = tmp_path / "data", tmp_path / "allowed"
    (data / "workspaces").mkdir(parents=True)
    allowed.mkdir()
    return SimpleNamespace(
        data_dir=data,
        config=SimpleNamespace(
            execution=SimpleNamespace(workspace_root=str(data / "workspaces")),
            security_infra=SimpleNamespace(read_roots=[str(allowed)]),
        ),
    )


async def _round(kind: str, bus: object, scene: SimpleNamespace, stored: str | None):
    """One intent through the real agent: (its IntentResult, the model, the agent's file). ``stored`` None: no file."""
    spec = KINDS[kind]
    target = scene.home / ".probos" / spec.file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if stored is not None:
        target.write_text(stored, encoding="utf-8")
    model = _Model(json.dumps({"action": "check", spec.key: [NEW]}))
    agent = spec.cls(agent_id=f"{kind}-1", llm_client=model, runtime=SimpleNamespace(intent_bus=bus))
    result = await agent.handle_intent(IntentMessage(intent=spec.intent, params={"action": "add"}))
    return result, model, target


async def _control(kind: str, scene: SimpleNamespace, bus: object) -> None:
    """Premise: a good read reaches the model and its list is written, so 'nothing written' below is not an inert harness."""
    result, model, target = await _round(kind, bus, scene, STORED)
    assert result.success is True and len(model.requests) == 1 and STORED in model.requests[0].prompt, "premise: the list is read"
    assert json.loads(target.read_text(encoding="utf-8")) == [NEW] and len(scene.writes) == 1, "premise: the model's list is written"
    scene.writes.clear()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("state", STATES)
async def test_through_the_real_readers_a_stored_missing_or_empty_file_still_works(scene, kind, state):
    """The seam: the file, the real readers, the agent's read, the model, the write."""
    result, model, target = await _round(kind, _Readers(), scene, STATES[state])
    assert result.success is True and len(model.requests) == 1
    assert (STORED if state == "stored" else f"{KINDS[kind].label}:\n[]") in model.requests[0].prompt
    assert json.loads(target.read_text(encoding="utf-8")) == [NEW] and len(scene.writes) == 1


@pytest.mark.parametrize(("shape", "shown"), [("found", f"Note 'My Note':\n{STORED}"), ("missing", "Note 'My Note' not found.")])
async def test_the_note_agent_reads_as_before(scene, shape, shown):
    agent = NoteTakerAgent(agent_id="note-1", llm_client=_Model(""), runtime=SimpleNamespace(intent_bus=_Bus(shape)))
    obs = await agent.perceive(IntentMessage(intent="manage_notes", params={"action": "read", "title": "My Note"}))
    assert obs["fetched_content"] == shown


async def test_the_reader_still_says_file_not_found_in_its_own_words(tmp_path):
    path = str(tmp_path / "absent.json")
    for intent in ("read_file", "stat_file"):
        answer = await FileReaderAgent(agent_id="fr-0").handle_intent(IntentMessage(intent=intent, params={"path": path}))
        assert (answer.success, answer.error) == (False, f"File not found: {path}")


class TestAFailedReadWritesNothing:
    # BF-961 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-961 M2 builds it")

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("shape", ["refused", "os-error", "mixed", "no-content", "nobody"])
    async def test_the_intent_is_refused_before_the_model_and_nothing_is_written(self, scene, kind, shape):
        await _control(kind, scene, _Bus("found"))
        result, model, target = await _round(kind, _Bus(shape), scene, STORED)
        assert result.success is False and result.error == f"Could not read {KINDS[kind].what}; nothing was changed or saved."
        assert model.requests == [] and scene.writes == []
        assert target.read_bytes() == STORED.encode("utf-8")

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("state", STATES)
    async def test_a_read_the_policy_refuses_writes_nothing(self, scene, kind, state):
        """BF-944's case without BF-944: the readers are built with a runtime whose read_roots omit ~/.probos."""
        await _control(kind, scene, _Readers())
        result, model, target = await _round(kind, _Readers(_confining(scene.tmp)), scene, STATES[state])
        assert result.success is False and result.error == f"Could not read {KINDS[kind].what}; nothing was changed or saved."
        assert model.requests == [] and scene.writes == []
        assert (target.read_bytes() if target.exists() else None) == (None if STATES[state] is None else STATES[state].encode("utf-8"))

    def test_the_guard_is_not_shadowed(self):
        assert TodoAgent.decide is not CognitiveAgent.decide and TodoAgent.decide is SchedulerAgent.decide
```

### 7.2 M2

**P2-1.** New file `src/probos/agents/utility/stored_list.py`:

```python
"""BF-961 (#1774): reading a bundled agent's stored list without reading a failure as an empty list.

TodoAgent and SchedulerAgent show the model the list stored in a file and write back the list it builds, so a read that
failed must never read as "no list". ``read_stored_list`` says which of three things a ``read_file`` broadcast told;
``UnreadableListGuard`` ends the intent before the model, and so before any write, when the read failed (the shape of
BF-769 and BF-772, ``web_agents._FetchGatedMixin``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from probos.agents.file_reader import is_file_not_found
from probos.types import IntentMessage

logger = logging.getLogger(__name__)

#: The observation key ``perceive`` sets, to the text the user is answered with, when the stored list could not be read.
UNREADABLE_KEY = "stored_list_unreadable"


class ReadStatus(str, Enum):
    FOUND = "found"  # a reader returned the file's text, which may be empty: the file exists
    MISSING = "missing"  # every answer is the reader's "no such file": nothing is stored yet
    FAILED = "failed"  # nobody answered, or an answer was a refusal or an error: what is stored is not known


@dataclass(frozen=True)
class ListRead:
    status: ReadStatus
    text: str = ""  # the file's text; empty unless FOUND
    reason: str = ""  # why, for the log; set when FAILED


async def read_stored_list(runtime: Any, path: str) -> ListRead:
    """Broadcast ``read_file`` for *path* and say what the answers told.

    The first success with text is the text (as before). Failing that, a success with no text is an existing empty file;
    answers that are all the reader's "no such file" are a file that is not there yet; anything else, including no answer
    at all, is a failure and is logged at WARNING.
    """
    bus = getattr(runtime, "intent_bus", None)
    if bus is None:
        return _failed(path, "the runtime has no intent bus")
    answers = await bus.broadcast(IntentMessage(intent="read_file", params={"path": path}))
    empty = False
    missing = 0
    reason = "no reader answered"
    for r in answers:
        if r.success:
            content = r.result
            if isinstance(content, dict):
                content = content.get("content", content.get("data", str(content)))
            if content:
                return ListRead(ReadStatus.FOUND, str(content))
            if content is None:
                reason = "a reader answered success with no content"
            else:
                empty = True
        elif is_file_not_found(r.error):
            missing += 1
        else:
            reason = f"a reader answered: {str(r.error)[:200]}"
    if empty:
        return ListRead(ReadStatus.FOUND)
    if answers and missing == len(answers):
        return ListRead(ReadStatus.MISSING)
    return _failed(path, reason)


def _failed(path: str, reason: str) -> ListRead:
    logger.warning("BF-961: %s could not be read (%s)", path, reason)
    return ListRead(ReadStatus.FAILED, reason=reason)


class UnreadableListGuard:
    """Mixin, ahead of ``CognitiveAgent`` in the bases: an agent whose ``perceive`` could not read its stored list answers
    so and does nothing else, so that no list the model builds is written over what is stored."""

    async def _stored_list(self, obs: dict, path: str, what: str) -> str | None:
        """The stored text ("" when there is none yet), or None after marking *obs* so that ``decide`` ends the intent."""
        read = await read_stored_list(self._runtime, path)
        if read.status is ReadStatus.FAILED:
            obs[UNREADABLE_KEY] = f"Could not read {what}; nothing was changed or saved."
            return None
        return read.text

    async def decide(self, observation: dict) -> dict:
        # No model call: ``act`` answers success False with this text, as it does for a failed model call.
        refusal = observation.get(UNREADABLE_KEY)
        if refusal:
            return {"action": "error", "reason": refusal}
        return await super().decide(observation)  # type: ignore[misc]
```

**P2-2.** `src/probos/agents/file_reader.py`
SEARCH:
```
logger = logging.getLogger(__name__)


class FileReaderAgent(BaseAgent):
```
REPLACE:
```
logger = logging.getLogger(__name__)

#: BF-961: the first words of the error a ``read_file`` or ``stat_file`` result carries for a path that does not exist.
FILE_NOT_FOUND_MARK = "File not found: "


def is_file_not_found(error: object) -> bool:
    """BF-961: whether *error*, the ``error`` of a ``read_file`` result, is this reader's answer for a path that is not there.

    A path the read policy refuses, an OS error and a path that is not a file carry other text. A caller that must tell a
    stored file that is not there yet from one it could not read asks here, and treats every other error as a failure."""
    return isinstance(error, str) and error.startswith(FILE_NOT_FOUND_MARK)


class FileReaderAgent(BaseAgent):
```

**P2-3.** `src/probos/agents/file_reader.py`
SEARCH:
```
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not p.is_file():
```
REPLACE:
```
            if not p.exists():
                return {"success": False, "error": f"{FILE_NOT_FOUND_MARK}{path}"}
            if not p.is_file():
```

**P2-4.** `src/probos/agents/file_reader.py`
SEARCH:
```
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}

            stat = p.stat()
```
REPLACE:
```
            if not p.exists():
                return {"success": False, "error": f"{FILE_NOT_FOUND_MARK}{path}"}

            stat = p.stat()
```

**P2-5.** `src/probos/agents/utility/productivity_agents.py`
SEARCH:
```
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
```
REPLACE:
```
from probos.agents.utility.stored_list import UnreadableListGuard
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
```

**P2-6.** `src/probos/agents/utility/productivity_agents.py`
SEARCH:
```
# ------------------------------------------------------------------
# Helper: mesh file I/O
# ------------------------------------------------------------------

async def _mesh_read_file(runtime: Any, path: str) -> str | None:
    """Read a file via mesh dispatch."""
    if not runtime or not hasattr(runtime, "intent_bus"):
        return None
    msg = IntentMessage(intent="read_file", params={"path": path})
    results = await runtime.intent_bus.broadcast(msg)
    for r in results:
        if r.success and r.result:
            content = r.result
            if isinstance(content, dict):
                content = content.get("content", content.get("data", str(content)))
            return str(content)
    return None


async def _mesh_write_file(runtime: Any, path: str, content: str) -> bool:
```
REPLACE:
```
# ------------------------------------------------------------------
# Helper: mesh file I/O (the read is stored_list.read_stored_list, BF-961)
# ------------------------------------------------------------------

async def _mesh_write_file(runtime: Any, path: str, content: str) -> bool:
```

**P2-7.** `src/probos/agents/utility/productivity_agents.py`
SEARCH:
```
class TodoAgent(_BundledMixin, CognitiveAgent):
```
REPLACE:
```
class TodoAgent(_BundledMixin, UnreadableListGuard, CognitiveAgent):
```

**P2-8.** `src/probos/agents/utility/productivity_agents.py`
SEARCH:
```
            path = os.path.expanduser(self._TODO_PATH)
            content = await _mesh_read_file(self._runtime, path)
            if content:
                obs["fetched_content"] = f"Current todos:\n{content}"
            else:
                obs["fetched_content"] = "Current todos:\n[]"
        return obs
```
REPLACE:
```
            path = os.path.expanduser(self._TODO_PATH)
            content = await self._stored_list(obs, path, "your todo list")  # BF-961: None: the read failed, ``decide`` ends the intent
            if content is not None:
                obs["fetched_content"] = f"Current todos:\n{content or '[]'}"
        return obs
```

**P2-9.** `src/probos/agents/utility/organizer_agents.py`
SEARCH:
```
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
```
REPLACE:
```
from probos.agents.utility.stored_list import UnreadableListGuard, read_stored_list
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
```

**P2-10.** `src/probos/agents/utility/organizer_agents.py`
SEARCH:
```
# ------------------------------------------------------------------
# Mesh file I/O helpers (same pattern as productivity_agents)
# ------------------------------------------------------------------

async def _mesh_read_file(runtime: Any, path: str) -> str | None:
    if not runtime or not hasattr(runtime, "intent_bus"):
        return None
    msg = IntentMessage(intent="read_file", params={"path": path})
    results = await runtime.intent_bus.broadcast(msg)
    for r in results:
        if r.success and r.result:
            content = r.result
            if isinstance(content, dict):
                content = content.get("content", content.get("data", str(content)))
            return str(content)
    return None


async def _mesh_write_file(runtime: Any, path: str, content: str) -> bool:
```
REPLACE:
```
# ------------------------------------------------------------------
# Mesh file I/O helpers (same pattern as productivity_agents; the read is stored_list.read_stored_list, BF-961)
# ------------------------------------------------------------------

async def _mesh_write_file(runtime: Any, path: str, content: str) -> bool:
```

**P2-11.** `src/probos/agents/utility/organizer_agents.py`
SEARCH:
```
                content = await _mesh_read_file(self._runtime, f"{notes_dir}/{filename}")
                if content:
```
REPLACE:
```
                # BF-961: a note that cannot be read shows as not found, as before (nothing is written after this read: L5)
                content = (await read_stored_list(self._runtime, f"{notes_dir}/{filename}")).text
                if content:
```

**P2-12.** `src/probos/agents/utility/organizer_agents.py`
SEARCH:
```
class SchedulerAgent(_BundledMixin, CognitiveAgent):
```
REPLACE:
```
class SchedulerAgent(_BundledMixin, UnreadableListGuard, CognitiveAgent):
```

**P2-13.** `src/probos/agents/utility/organizer_agents.py`
SEARCH:
```
            path = os.path.expanduser(self._REMINDERS_PATH)
            content = await _mesh_read_file(self._runtime, path)
            parts = []
```
REPLACE:
```
            path = os.path.expanduser(self._REMINDERS_PATH)
            content = await self._stored_list(obs, path, "your saved reminders")  # BF-961: None: the read failed, ``decide`` ends the intent
            if content is None:
                return obs
            parts = []
```

**N2-1.** `tests/test_bf961_unreadable_stored_list.py`
SEARCH:
```
    # BF-961 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-961 M2 builds it")

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("shape", ["refused", "os-error", "mixed", "no-content", "nobody"])
```
REPLACE:
```
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("shape", ["refused", "os-error", "mixed", "no-content", "nobody"])
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-961 (DATE), #1774 -- the todo and scheduler agents refuse an intent whose stored list could not be read.**
- **Base.** `_mesh_read_file` returned `None` for a read that failed, was refused or found nothing; the two agents showed the model `[]`, and the list it built from that replaced `~/.probos/todos.json` or `reminders.json`. A refused read (BF-944 will apply `read_roots` to the file pools), an OS error, a closed bus and an unanswered broadcast all read as an empty list.
- **Fix.** New `agents/utility/stored_list.py`: `read_stored_list` says a file was found (empty included), missing (every answer is the reader's `File not found:`, now `FILE_NOT_FOUND_MARK` in `agents/file_reader.py`) or failed. After a failed read the agents answer `Could not read ...; nothing was changed or saved.` (`success` False) before the model and any write. The note agent reads through the helper; its text is unchanged. Contract `prompts/bf-961-unreadable-stored-list.md`. Closes #1774.

```

**P3-2.** `DECISIONS.md`. Append after BF-945's entry (the last on `50caed13`). Its last bullet occurs once.
SEARCH:
```
- *Residual.* L1 to L8 of the contract. *Reversal.* Revert the BF-945 commits.
```
REPLACE:
```
- *Residual.* L1 to L8 of the contract. *Reversal.* Revert the BF-945 commits.

### BF-961 -- The todo and scheduler agents refuse an intent whose stored list could not be read (DATE, #1774)

- *Scope.* `agents/utility/stored_list.py` (new), `agents/file_reader.py` (`FILE_NOT_FOUND_MARK`, `is_file_not_found`), `TodoAgent`, `SchedulerAgent` and the note agent's read, tests. Contract `prompts/bf-961-unreadable-stored-list.md`.
- *G1 (missing or failed).* The reader's own `File not found:` text through one constant it owns; every other answer, and no answer, is a failure. Rejected: `stat_file` (the same shape); a reader-set `metadata` field (a wider change); an `exists()` probe by the agent (a second source of truth beside the read policy).
- *G2 (the intent).* A shared `decide` ends the intent before the model: no model call, no write, `success` False. Rejected: running the model and refusing only the write; telling the model the list is unavailable; two copies.
- *G3 (the note agent).* It reads through the helper, its text unchanged; a failed read still reads "not found" (no write depends on it). *G4 (the write).* `commit_write` is unchanged.
- *Residual.* L1 to L8 of the contract. *Reversal.* Revert the BF-961 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

`FileWriterAgent` (`commit_write`, the proposal path) and both `_mesh_write_file` (BF-911's inventory names them by scope); both `act` bodies; the note agent's `save`, `list` and `search`; `_mesh_list_dir`; `FileReaderAgent`'s behaviour and result shapes (its two not-found answers carry the same text), `security/file_access.py` and the read policy; `IntentBus`, `CognitiveAgent` and its decision cache; the operations `SchedulerAgent` (`agents/operations/scheduler.py:78`, another class); the pools (`startup/agent_fleet.py`: BF-944 hands the file pools the runtime), `config.py`, the roadmap, every document; AD-1346's census rows. OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/agents/utility/stored_list.py | `if refusal:` | `if False:` | T1, T2 |
| 2 | M2 | src/probos/agents/utility/stored_list.py | `elif is_file_not_found(r.error):` | `elif True:` | T1[refused, os-error, mixed], T2 |
| 3 | M2 | src/probos/agents/utility/stored_list.py | `if answers and missing == len(answers):` | `if missing == len(answers):` | T1[nobody] |
| 4 | M2 | src/probos/agents/utility/stored_list.py | `if answers and missing == len(answers):` | `if answers and missing:` | T1[mixed] |
| 5 | M2 | src/probos/agents/utility/stored_list.py | `if content is None:` | `if False:` | T1[no-content] |
| 6 | M2 | src/probos/agents/utility/stored_list.py | `return ListRead(ReadStatus.FOUND, str(content))` | `return ListRead(ReadStatus.FOUND)` | T1, T2 (their control), T4[stored], T5[found] |
| 7 | M2 | src/probos/agents/utility/stored_list.py | `empty = True` | `empty = False` | T4[empty] |
| 8 | M2 | src/probos/agents/file_reader.py | `return isinstance(error, str) and error.startswith(FILE_NOT_FOUND_MARK)` | `return False` | T4[missing] |
| 9 | M2 | src/probos/agents/utility/productivity_agents.py | `class TodoAgent(_BundledMixin, UnreadableListGuard, CognitiveAgent):` | `class TodoAgent(_BundledMixin, CognitiveAgent):` | T1[todo], T2[todo], T3, T4[todo] |
| 10 | M2 | src/probos/agents/utility/organizer_agents.py | `class SchedulerAgent(_BundledMixin, UnreadableListGuard, CognitiveAgent):` | `class SchedulerAgent(_BundledMixin, CognitiveAgent):` | T1[scheduler], T2[scheduler], T3, T4[scheduler] |
| 11 | A1 | src/probos/agents/utility/stored_list.py | `if isinstance(content, dict):` | `if False:` | T7[dict-false, dict-none, dict-blank-then-text], T5[the same three] |
| 12 | A1 | src/probos/agents/utility/stored_list.py | `if content:` | `if content is not None:` | T7[dict-empty], T5[dict-empty] |
| 13 | A1 | src/probos/agents/utility/stored_list.py | `reason = f"a reader answered: {str(r.error)[:200]}"` | `return _failed(path, f"a reader answered: {str(r.error)[:200]}")` | T7[found-beside-failure], T5[found-beside-failure] |

Run by hand against the patched modules (no pytest): each mutant fails the cases it names, rows 9 and 10 with `AttributeError` (`_stored_list` is gone from the class). No campaign of record: the Builder runs the 10 mutants once, on M2's head, with the new file alone. Not tabulated, for the cap: the note agent's read line (T5), the refusal text, and the `bus is None` guard (without it `None.broadcast` raises and nothing is written).

## 10. Recorded limits

- **L1.** The guard is per agent, not per action. With `reminders.json` unreadable, `list` and a `remind` that needs only the task stores answer the unreadable text too (no model request, no task created). `act` writes `reminders`, when the model's object carries them, after each action but `list` and a `cancel` that names a task on a runtime with a scheduler, and the file is the model's context for `check` (`organizer_agents.py:251-281`, `:322-347`). A per-action rule is a follow-up.
- **L2.** A read that succeeds is not checked: a file truncated by a crash or edited by hand is shown to the model as text. `commit_write` is unchanged (D4): a crash during `write_text` can truncate the file, and a model that returns a shorter list replaces it; no backup.
- **L3.** The user is told only the fixed text; the reason (the policy's words, an OS error) is in the WARNING `BF-961: <path> could not be read (<reason>)`. A refused intent counts as a failure in the agent's confidence (`cognitive_agent.py:7955`), as `Failed to save` does.
- **L4.** After BF-944, with `read_roots` set and `~/.probos` unlisted, `manage_todo` and `manage_schedule` answer the unreadable text and write nothing, a first save included: the refusal comes before the existence check (measured, section 11). BF-944's contract says otherwise and must change when re-anchored. Its P2-5 comment sentence "a refused read of the todo or reminder file reads as an empty list, and the next save replaces the stored one" becomes "a refused read of the todo or reminder file makes those agents answer that the list could not be read, and write nothing (BF-961)". Its L6 sentence "The todo and scheduler agents read the refusal as an empty list (...) and their next save writes the list they build, replacing the stored one" becomes "The todo and scheduler agents answer that the list could not be read and write nothing (BF-961), a first save included". T2 runs this case today with a reader built with the runtime (BF-758's `runtime=` keyword).
- **L5.** The note agent's `read` still answers `Note '<title>' not found.` for a failed read (the BF-769 class of honesty gap), and the model sees that answer. No code writes what the read returned: on the tree of this change `act` writes only from the model's own JSON (`organizer_agents.py:164-188`). But `act` saves whenever that JSON says `"action": "save"`, whatever action was requested, so a requested `read` whose model answer says `save` writes the note it names: run on `6ee2bfa0` and on `d9b2a9da` (review round 1), a requested `read` of an existing note and such an answer made one `commit_write` call and changed the stored note. That is not new and is not fixed here (the requested action is not checked at the write): a follow-up. The one new effect of this change is the WARNING.
- **L6.** The mark is text. A reader that words its not-found answer otherwise reads as failed, which fails closed and loudly (a first save is refused, WARNING); T4 and T6 fail first. A file removed between the reader's existence check and its read answers with the OS error and reads as failed (`file_reader.py:134-147`). An answer from a federated peer counts as a reader's (federation is off by default, `config.py:2477`; not traced).
- **L7.** The read's broadcast waits the intent's 60 s TTL (`types.py:65`, `intent.py:1467`) and drops a later answer: a good read that arrives late reads as no answer, and the intent is refused with the WARNING. A request that reaches the agent as a DAG node is submitted with a 10 s timeout (`decomposer.py:1039-1043`), so in that path the caller's own timeout comes first; what the agent does after it was not traced.
- **L8.** Nothing here is a live-system claim: no vessel, no real model and no real `~/.probos` was used; that a model builds its list from `[]` is by the agents' instructions (`productivity_agents.py:133-145`).
- **L9.** A success whose result is empty, is not None and is not a string (`{}`, `[]`, `0`, `False`, `b""`) reads as an existing empty file (FOUND, empty): `[]` is shown (T7[dict-empty]) and the model's list is written (the write is `act`'s, unchanged; T4[empty] pins it for an empty file), as after the old read, which returned None for such a result, as it did for an empty string. The real reader answers a string (`file_reader.py:79`, `:154`), so only a double or a federated peer's answer (L6) reaches this. Not hardened here: a follow-up.

## 11. Verified Against Codebase (2026-11-08, reading tree `D:\ProbOS-worktrees\bf944-base` at `6ee2bfa0`)

**Run by the Architect, read-only (CPython 3.12.13, win32; scripts and scenes in the OS temp folder, outside every repository, removed afterwards; `-B`; no pytest and no test function):**

```
git rev-parse HEAD (bf944-base) and origin/main -> both 6ee2bfa0bd562fb8bd45c4069ee33ea5551be64d (PR #1773's merge); git status of the reading tree empty after the runs
the real FileReaderAgent through handle_intent, HOME moved: found -> success True, result '[1]'; an empty file -> True, ''; a missing path -> False, None, 'File not found: <path>'; a directory -> False, 'Not a file: <path>' (stat_file True); a runtime whose read_roots omit the path -> False, 'path is outside every readable root', for an existing and for a missing path, and the same text from stat_file; read_text raising PermissionError -> False, "[Errno 13] Permission denied: '<path>'"; metadata {} in every case
AST of the two helper copies: the bodies and arguments of _mesh_read_file and of _mesh_write_file are identical; only the read helper's docstring differs
this contract's 13 pairs and 2 new files applied in label order to the LF blobs: every SEARCH once; every result parses; the blocks are ASCII; the patched modules and the test module exec'd over the real tree; the cases driven by hand: base 9 of 26 hold, the 17 class cases failing at their first assert with the control round passing; M2 26 of 26; the ten mutants of section 9 as listed there; the operations of test_utility_agents.py (handle_intent and perceive without a runtime, self-deselect, act persisting to tmp files, a write failure) driven by hand on the patched agents: all hold
```

**Absence Verified (2026-11-08)**

```
CLAIM: no BF-961 other than #1774; the highest before it is BF-960
RUN:   git log --all subjects and --grep; prompts/bf-961* in each of the 123 worktrees of git worktree list; gh issue list --state all --search "BF-961 in:title" (and BF-962 to BF-965); git grep BF-961 over HEAD and origin/main; the highest BF in git log --all subjects
FOUND: 0 and 0; 0; #1774 only (OPEN, bug), none for 962 to 965; one hit, the generated "Next free" row open-ads-report.md:32; BF-960
HOLDS: yes

CLAIM: _mesh_read_file has the three call sites cited and no other consumer
RUN:   git grep -n -E "_mesh_read_file|_mesh_write_file|def _mesh_" -- src tests scripts docs config
FOUND: both definitions; reads at productivity_agents.py:169, organizer_agents.py:136, :255; writes at :189, :191, :349; test_ad1344_constitution_write_refusal.py:30,680,682; test_bf911_...:738-742,960-961; roadmap-completed.md:53 (a mention)
HOLDS: yes

CLAIM: nothing but the two agents reads todos.json or reminders.json
RUN:   git grep -n -E "_TODO_PATH|_REMINDERS_PATH|todos\.json|reminders\.json" -- src ui/src config scripts; then the same over the repository
FOUND: the agents' perceive and act only; elsewhere the era trackers, archived prompts, BF-919's R-1 and tmp_path files in test_utility_agents.py:763,805,827; no document under docs/
HOLDS: yes

CLAIM: no test names the model-facing strings; no AD-1346 census row names an edited file
RUN:   git grep -n -E "Current todos|Saved reminders|_mesh_read_file|Failed to save (todos|reminders)" -- tests; git grep -n -E "file_reader|FileReaderAgent|productivity_agents|organizer_agents|agents/utility" -- 'tests/fixtures/ad1346_*' 'tests/test_ad1346*'
FOUND: 0; 1 (avatar_agents.py, ad1346_file_write_census.py:165). AD-1346's effect classes are model call, subprocess, egress and store write (admission/taxonomy.py:23-33) and its file-write points are listed at ad1346_file_write_census.py:3-19; the new and edited code holds none (by reading), so no row or anchor changes
HOLDS: yes

CLAIM: the tests that touch the agents, the helpers or the reader are the files of G2
RUN:   git grep -n -E "_mesh_read_file|_mesh_write_file|TodoAgent|SchedulerAgent|NoteTakerAgent|manage_todo|manage_schedule|manage_notes" -- tests src; Grep "FileReaderAgent|agents\.file_reader|agents/file_reader" over tests
FOUND: test_utility_agents, test_task_scheduler, test_ad686_oracle_semantic_tier, test_ad1344, test_bf911, test_distribution (names; the class TestUtilityRuntimeIntegration boots the pools), test_llm_client (the mock decomposer's text) and test_ad467_operations_crew (the other SchedulerAgent, agents/operations); the 11 reader files: ad1026, ad152, ad983a, agent_tiers, bf758, bf908, cognitive_agent, consensus_integration, file_reader, prompt_builder, workflow_cache. test_llm_client and test_ad467_operations_crew are not in G2 (a text of the mock decomposer; another class). The four agents of test_utility_agents.py that get a spec'd runtime (:764, :785, :806, :826) call act only, so row 7 of section 1 changes no existing test
HOLDS: yes

CLAIM: the new names are free; no subclass of the three agents
RUN:   git grep -n -E "\bReadStatus\b|\bListRead\b|read_stored_list|UnreadableListGuard|UNREADABLE_KEY|FILE_NOT_FOUND_MARK|is_file_not_found|stored_list" -- src tests scripts docs config; git grep -n -E "class \w+\(.*(TodoAgent|NoteTakerAgent|SchedulerAgent)" -- src tests
FOUND: 3 hits, a local variable in scripts/check_config_facade.py:1645-1648; the bundled classes and agents/operations/scheduler.py:78 only
HOLDS: yes
```

**Read, not run:** `intent.py:1355`, `:1368`, `:1467-1477`, `:1901-1906`; `cognitive_agent.py:3743`, `:3746-3751` (the decision cache, default off), `:7565`, `:7595`, `:7758`, `:7853`, `:7955`, `:8013`; `web_agents.py:288-388`; `file_writer.py:146-164`; `agent_fleet.py:47`, `:57`, `:109-117`; `decomposer.py:476`, `:759`, `:764`; the layer rules of `scripts/check_architecture_principles.py` and `test_layer_boundaries.py:50` (`agents` imports `substrate` and `cognitive`; the new module imports `agents.file_reader` and `types` only). **Not measured:** a live vessel; a real model.

## 12. Prior Art and Blind Spots

- **Internal: adopted.** BF-769 and BF-772 (`perceive` flags, `decide` ends the intent before the model, `act` answers `success` False; a richer outcome replaces a status-dropping helper, which is deleted; a structural guard that the gate is not shadowed); `decide`'s own error decision (`cognitive_agent.py:3743`); the mark-and-predicate idiom of `tools/protocol.py:97-114`; BF-758's `runtime=` keyword to build a confined reader; BF-911's inventory (unchanged). **Rejected:** a second copy; `stat_file`; a `metadata` flag; a local probe. **External:** none consulted.
- **Blind spots handled.** First use and an empty file through the real readers (T4); a refusal, an OS error, nobody, a mix and a success with no content (T1); the policy refusal of BF-944's configuration (T2); the decision cache and procedural memory (the guard returns before them); both agents; the note agent's text (T5); a dictionary result and a success beside a failure (T7).
- **What discards a correct result.** A good read refused: a reader answer later than the TTL (L7), a reader that words not-found otherwise (L6), a runtime double without `intent_bus`; each fails closed with the WARNING. A good read not shown: none found (a success's text is returned as `_mesh_read_file` returned it). **Recorded:** L1 to L9.

## 13. Diff Reviewer: properties to verify

1. `UnreadableListGuard.decide` returns before `super().decide`; with the key set, no model request is made and the first line of each `act` answers `{"success": False, "error": <text>}`. Trace `handle_intent` to the `IntentResult` (`cognitive_agent.py:7853`, `:8013`) and confirm no `commit_write` is reachable from `perceive` or `decide`.
2. `read_stored_list`, for each row of section 1: FOUND with the first non-empty success's text (as `_mesh_read_file` returned); MISSING only when the broadcast is non-empty and every answer passes `is_file_not_found`; FAILED otherwise, a success with `result` None included; the WARNING names the path and a reason, not content.
3. `TodoAgent` and `SchedulerAgent`: the bases are `(_BundledMixin, UnreadableListGuard, CognitiveAgent)`; the text shown for FOUND and MISSING is byte-identical to before (`Current todos:\n...` and `\n[]`; `Saved reminders:` likewise); the scheduler returns `obs` before gathering tasks only after a failed read.
4. `_mesh_read_file` is gone from both modules and nothing imports it; both `_mesh_write_file` and BF-911's T32 to T34 inventory are untouched.
5. `file_reader.py`: the two literals became `FILE_NOT_FOUND_MARK + path` with identical text; `is_file_not_found` is read only by `stored_list`; nothing else of the reader changes.
6. The note agent's observation is byte-identical for every row of section 1 (the note's text, `not found` otherwise); the one new effect is the WARNING.
7. M1: the file collects on the unfixed tree, imports no BF-961 name, and the 17 class cases fail at their own `assert`, never at a premise line; N2-1 removes the marker only.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **A failed or refused read** (rows 4 to 7 and 9 of section 1): `manage_todo` and `manage_schedule` answer `success` False with `Could not read ...; nothing was changed or saved.`, make no model request and no `commit_write`, and leave the stored bytes unchanged (T1, T2).
- **First use and an empty file:** the model is shown `[]`, the save creates or replaces the file, also through the real readers (T4); the note agent's text and the reader's `File not found:` text are unchanged (T5, T6).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
