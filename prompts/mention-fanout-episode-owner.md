# The @-mention fan-out stores each reply as the replying agent's own episode: BF-964 (#1794), one slice

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-13
**Revised by:** amendment A1 (section 15: the oracle's measurements; the base moved to the merge of #1795; one pair added, P2-14 (the new file's docstring); the Killed-by cells of mutation rows 6 and 11, the last sentence of L11, the range of the message scans, the Captain paragraph and two phrases of the `PROGRESS.md` entry corrected), measured and applied by the orchestrator, 2026-11-14
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14 (amendment A2: review round 1 triaged; no code change; L5 amended and L12 to L14 added in section 10; the two tracker entries name them)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14 (amendment A3: review round 2 triaged; no code change; L12 and section 16 corrected; the gate's owner-blindness filed as #1798)
**File in the repository:** `prompts/mention-fanout-episode-owner.md` (the orchestrator may rename it; the heads and subjects of this slice carry no `AD-` or `BF-` token, section 5).
**Status:** ready to build on `origin/main` `5275d008` (the merge of #1795: item B and GATE-F3 of #1754; its tree `a21ff7fb` is the gated tree).
- **Reading tree:** `D:\ProbOS-worktrees\next-read` at `c408860b` (item B's head), as the Architect read it. The files this slice edits are the same on `c408860b`, `2b4b783a` and `5275d008`: `git diff --stat 2b4b783a c408860b -- src/probos/routers/chat.py tests/test_ad791g_main_chat_thread.py tests/test_ad719_episodic_writes.py tests/test_bf813_denial_consumers.py src/probos/cognitive/episodic.py src/probos/types.py` printed nothing, and their blobs on `5275d008` equal the base blobs below.
- **Oracle:** run by the orchestrator after the Architect's draft (section 15): every block of section 7 applied by tool to a scratch tree whose tree equals `5275d008`'s, with the focused gates and the mutation rows measured there. The Architect's consult was read-only (no pytest, no script that writes, no in-memory apply); section 11 records what it read.

**Base blobs.** These are equal on `2b4b783a`, `c408860b` and `5275d008`.

*Edited:*
- `src/probos/routers/chat.py` `b932b7b118fc041f560dcdbec1dc8ad37c320352`
- `tests/test_ad791g_main_chat_thread.py` `a0c988d1a80a2c2befe951182d8cfeb3b73cf6a2`
- `tests/test_ad719_episodic_writes.py` `811743a6e7638d22ddbccebde7ac2d0f53aef892`
- `tests/test_bf813_denial_consumers.py` `8ffa9ad1c36fd77464ea3f62a848528f52439640`

*Read, not edited:*
- `src/probos/dream_adapter.py` `832fc0aa1eef9d2ef35a78ca2f42507aee4993a9`
- `src/probos/cognitive/episodic.py` `279fba1b5d107594c7b70bb5005512f810ea3c5d`
- `src/probos/routers/thread_fanout.py` `7560fa54c7b31d56776af9aba10d483c31b75df9`

*Trackers (they differ and move with merges):*

| Tracker | `5275d008` (the base to build on) | `c408860b` | `2b4b783a` |
|---|---|---|---|
| `PROGRESS.md` | `3e87baf3c6aa2b23ca4ab5a8e39303915406c2ee` | `8336e3b3bdbd190bad37434059dec69b19a8052f` | `9bb3f09a8b37fe8d26119186e23c83a3f507dc2c` |
| `DECISIONS.md` | `675bdc29f9bafaa0dbcb2145176e25060e0a4e2f` | `2c3cdcf2a67e9a73cfa22bc8d3e25f4764c98fd5` | `9f4327c9a3fa1e201bca8c5d9faad3c4f74cc834` |

*Paths that do not exist (Glob found none):* `tests/test_mention_fanout_episode_owner.py`, `prompts/mention-fanout-episode-owner.md`, `prompts/bf-964*`.

**Dependencies:** none in code. The batch of #1795 has merged, so the trackers are at their `5275d008` blobs above (anchors below).

**Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD (D1).

**Estimated tests (expected, not measured):**
- One new file with 5 cases: 1 control passes at M1 and 4 xfail.
- Three existing files are edited with inline reasons, and no test function is removed.
- No config key and no config model. The only generated artifact is the AD ledger pair.

**Numbers (hard rule):**
- **Current highest AD: AD-1359.** `d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py` gave the same value from `git log --all` subjects, from GitHub issue titles in all states (1,520 issues, not truncated) and from `prompts/ad-*.md`. Next would be AD-1360.
- **Current highest BF: BF-964.** #1794's title reads `BF-964: ...`, checked with `gh issue view 1794`. #1793 is BF-963. In git subjects the highest is BF-961 (`git log --all -E --grep "^BF-96[0-9]"`).
- **Nothing is allocated here.** BF-964 is #1794's number and is already filed.

**Tracker anchors.** The merged batch inserted one entry into each tracker before these same anchors, so this slice's entries land before them too.
- `PROGRESS.md`: the title line `# ProbOS Progress` and the blank line after it. It occurs once (Grep count 1, line 1).
- `DECISIONS.md`: the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)`. It occurs once, at line 1788 on `c408860b` and at line 1796 on `5275d008`.
- No tracker line and no commit subject of this slice carries an `AD-` or `BF-` token.

## 1. Problem

The route builds the episode for an @-mention fan-out reply with the wrong builder. That builder reads none of the keys the route gives it.

| Claim (source) | Re-derived on `c408860b` | Verdict |
|---|---|---|
| With an adapter present, the route calls `dream_adapter.build_episode(episode_input, {"response": reply.text, "agent_ids": [reply.agent_id]}, t_start_fanout, t_end_fanout)` (#1794) | `routers/chat.py:358` reads `dream_adapter = getattr(runtime, "dream_adapter", None)`; `:364-370` is the call; `:371-385` is the branch without an adapter (`agent_ids=[reply.agent_id]`, `source="multi_agent_chat"`, `AnchorFrame(channel="chat", trigger_type="at_mention_fanout")`, `outcomes=[]`, no reflection) | **Holds** |
| `build_episode` reads only `dag`, `results` and `reflection` | `dream_adapter.py:355-356` and `:388`. `agent_ids` and `outcomes` are filled only inside `if dag and hasattr(dag, "nodes")` (`:362-386`). `source=MemorySource.DIRECT` (`:417`); the frame is `channel="dag", trigger_type="dag_execution"` (`:418-422`) | **Holds.** It also copies `_last_shapley_values` (`:391`) and the trust events since `t_start` (`:394-405`); see L3 |
| A started vessel has an adapter | `startup/finalize.py:6214` builds `DreamAdapter(` at function-body indent; `runtime.py:3721` sets `self.dream_adapter = fin.dream_adapter` | **Holds** (read, not run) |
| The thread-id replace runs after the if/else | `chat.py:386-409`: `dataclasses.replace` sets `chat_thread_id=MAIN_CHAT_THREAD_ID` when `_main_thread_store is not None` | **Holds** |
| The group-chat fan-out met the same trap and builds its Episode directly | `routers/thread_fanout.py:1095-1144` (AD-933a comment `:1095-1102`); reflection `"<callsign> said in group chat: <text[:_refl_cap]>"` (`:1130-1133`); `_refl_cap` is 600 when enrichment is on, otherwise 240 (`:1057`); `agent_ids=[reply["agent_id"]]`, the raw key (`:1115`) | **Holds** |
| Per-agent recall keeps an episode only if its owner is in `agent_ids` | `episodic.py:3974-3979` (`is_owned = agent_id in agent_ids`) and `:3992-3993` | **Holds** |
| The tests hid it | `test_ad719_episodic_writes.py:37-39` forces `rt.dream_adapter = None`. `test_ad791g_main_chat_thread.py:74-96` uses a fake `build_episode` that copies `agent_ids`, which the real function does not, and `:312` asserts `channel == "dag"`, which pins the defect. `test_bf813_denial_consumers.py:389` forces `None` | **Holds** |
| *New:* `test_bf813_denial_consumers.py` would break on the fix | `_base_runtime` is a `MagicMock` (`:101-113`). `_episode_agents` compares stored `agent_ids` with `[["counselor-001"], ["ops-001"]]` (`:412-413`, `:429`, `:441`, `:473`, `:496`). Once the route reads `runtime.identity_registry`, a `MagicMock` registry is truthy and `get_by_slot` returns a mock certificate, so the owner would be a mock (`episodic.py:480-484`) | **A required edit** (P2-11) |

## 2. Solution

One slice in three milestones.

- **M1** adds a test file. It drives the real route handler `routers.chat.chat` with a **real** `DreamAdapter`, a **real** `EpisodicMemory` on `tmp_path`, a real `CallsignRegistry`, a real `ChatThreadStore` and an identity registry double that maps slot ids to sovereign ids. It reads the stored rows back and recalls each episode as its owner by the reply's words. The cases that fail on the base are strict xfail at an `assert`.
- **M2** deletes the adapter branch. It builds one `Episode` directly, with no if/else:
  - owner: `resolve_sovereign_id_from_slot(reply.agent_id, runtime.identity_registry)`;
  - the reply in `outcomes` (`reply.text[:500]`) and in `reflection` (`"<callsign> said: <reply.text[:600]>"`);
  - source: `multi_agent_chat`;
  - frame: `chat` / `at_mention_fanout` with participants `["captain", <callsign>]`.

  The existing thread-id replace and the store follow, unchanged. M2 also updates the three existing test files that forced or faked the branch, each with its reason inline, turns the marker off and brings the new file's docstring up to date.
- **M3** is the trackers and the ledger.

## 3. Decisions

Each table ranks the options by correctness, safety, compatibility, fit, reversibility and validation cost; the first row is the decision. In-envelope means: evidence-backed, backward compatible, no weakened control, no OSS/commercial boundary crossed, bounded rollback. All of D1 to D8 are inside the envelope.

**D1. Slicing and tiers.**

| # | Option | Judgement |
|---|---|---|
| 1 | **One slice: M1 tests, M2 route plus pinned tests, M3 trackers** | One defect in one loop; one revert range undoes it |
| 2 | Pinned-test edits in M1 | Test 4 of AD-791g and the BF-813 registry pin both describe post-fix behaviour; at M1 the first would fail and the second's comment would be false |

**Tiers.**
- **M1 STANDARD:** tests only.
- **M2 HIGH:** it changes what episodic memory stores for every @-mention reply on a started vessel: owner, text and frame. The loop swallows every error at WARNING (`chat.py:410-415`), so a regression drops episodes silently. Review it with the Diff Reviewer.
- **M3 STANDARD.**

**D2. The shape (my 05:53Z decision, option a-prime).**

| # | Option | Judgement |
|---|---|---|
| 1 | **Delete the adapter branch; one direct `Episode` construction, no if/else** | The two-branch trap cannot recur. This is the group fan-out's AD-933a remedy and the shape the vision branch uses (`chat.py:759-798`) |
| 2 | Keep the branch and give `build_episode` a plan-shaped dict | Still writes `source=direct` and the `dag` frame, and attaches another consensus's Shapley values (L3) |
| 3 | Teach `build_episode` a chat shape (option b) | Gives a DAG builder a second input format; both other callers pass a plan (`runtime.py:6150`, `experience/renderer.py:486`). Rejected |
| 4 | A helper shared by both fan-outs (option c) | Widens the change into AD-933a's tested group construction (`test_ad933a_group_episode.py`). Deferred: a candidate once both shapes are stable |

**D3. The owner.**

| # | Option | Judgement |
|---|---|---|
| 1 | **`resolve_sovereign_id_from_slot(reply.agent_id, runtime.identity_registry)`** | The sovereign id where the slot has a certificate, otherwise the slot id (`episodic.py:474-485`). The Ward Room stores its posts' episodes the same way (`ward_room/messages.py:328-329`, `ward_room/threads.py:578-579`). `runtime.identity_registry` is a public attribute set in `__init__` (`runtime.py:1240`) and read directly by `routers/agents.py:199-202` |
| 2 | The raw slot id (the old branch without an adapter, and the group path) | The owner would not match a sovereign-keyed recall until the start-up migration rewrites it, and that runs only conditionally (L2) |
| 3 | Resolve inside `EpisodicMemory.store` for every writer | Changes every store path; its own item |

**D4. The text and the frame.**

| # | Option | Judgement |
|---|---|---|
| 1 | **`reflection = f"{speaker} said: {reply.text[:_MENTION_REFLECTION_MAX_CHARS]}"`, with `_MENTION_REFLECTION_MAX_CHARS = 600` a module constant of `chat.py`; `outcomes[0]["response"] = reply.text[:500]`; `participants=["captain", speaker]`; `speaker = reply.callsign or owner_id`** | 600 is the cap the group fan-out applies as shipped: `group_episode_enrichment_enabled: true` and `group_reflection_max_chars: 600` (`config/system.yaml:141-142`), and the model default is also 600 (`config.py:1069`). The 500 for the outcome copies the group (`thread_fanout.py:1110`). The reflection is what gets indexed: the embedded document includes it (`episodic.py:4433-4458`), and the FTS5 note at `thread_fanout.py:1120-1125` says the same. Participants hold callsigns: `AnchorFrame.participants` is documented "Callsigns present/involved" (`types.py:522`), the participant index writes each participant as its own callsign (`participant_index.py:100-105`), and the group path uses `["captain"] + callsigns` (`thread_fanout.py:1052`). **This revises my 05:53Z `participants=[sovereign]`; the sovereign id is already the episode's owner** |
| 2 | Read the group's config keys (`memory.group_episode_enrichment_enabled`, `memory.group_reflection_max_chars`) | Couples a `group_` key to a non-group path. On the `MagicMock` runtimes of three test files, `int(<mock>)` silently caps the reflection at 1 character |
| 3 | 240 (the group's cap with enrichment off) | Diverges from the shipped group episodes |

**D5. The thread-id replace stays** (`chat.py:395-409` unchanged). Its comment lines `:386-394` are rewritten (the TRAP no longer exists). Folding the id into the constructor would be equivalent; the vision branch does that (`:796`). It is rejected only because `:395` carries a non-ASCII arrow, so deleting it needs a SEARCH the ASCII rule forbids.

**D6. The existing tests that pinned the branch.** Update them with an inline reason and delete none.

| File | Change | Why |
|---|---|---|
| `test_ad791g_main_chat_thread.py` | The fake adapter counts its calls; Test 4's second half asserts `channel == "chat"` and zero calls; the factory sets `identity_registry = None`; the comments are rewritten | `:312` pinned the defect. A `MagicMock` registry would make the owner a mock |
| `test_ad719_episodic_writes.py` | The fixture no longer forces `rt.dream_adapter = None` (replaced by a comment) | The route no longer reads the adapter, so the fixture now runs the production shape |
| `test_bf813_denial_consumers.py` | `_fanout_runtime` sets `rt.identity_registry = None`, with a comment | Without it, four cases compare mock owners (section 1) |

Rejected: a production guard against mock registries (it is a test-double problem, and `resolve_sovereign_id_from_slot`'s no-registry behaviour is the documented fallback).

**D7. Episodes already stored without an owner: no backfill.** Such an episode holds the Captain's words in `user_input` but not the reply (`build_episode` drops `response`). An owner added later would give the agent a memory of a question with no answer. Finding these rows also needs a heuristic (`source` direct, `dag` frame, empty `agent_ids_json`, empty `dag_summary_json`, `user_input` starting `@`). The count on a **copy** of a vessel's data is still owed under #1794's acceptance (section "Not in this issue"). It goes to the Architect, is not published, and does not change this decision unless it shows rows that carry a reply.

**D8. The paperwork.** No number in any head:
- tracker heads start with a word;
- commit subjects start `Mention fan-out episode owner`;
- every message ends its body with `Refs #1794.`;
- no message uses a closing keyword, even to deny it;
- the pull-request body carries `Closes #1794` only once the D7 count has been taken and reported. Otherwise it says `Refs #1794`, and the issue stays open for that item.

`gen_ad_ledger.py` reads a tracker line only when, after markup, it starts with `AD-`, `BF-`, `AD ` or `BF ` (`scripts/gen_ad_ledger.py:209-211`), so no ledger number moves.

**D9. Public text.** No crew name, thread id, timestamp, live count or vessel line appears in any test, comment, tracker line or commit message. The new file's fixtures are synthetic: callsigns `TestAlpha`, `TestBravo`, `TestCharlie`; slots `test_*_officer_test_0_*`; sovereigns `sov-test-*`.

**One exception, named:** the SEARCH texts of P2-3 to P2-8 quote existing lines of `test_ad791g_main_chat_thread.py`. They name no callsign, but that file's untouched cases use three crew callsigns already in the repository (`:59-61`). The REPLACE text adds none.

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. Run every command from the repository root. **The Builder** runs only the focused pytest files of G1 and G2 (always `-n 0`) and the architecture check. **The orchestrator** runs the broad gate, the mutation campaign, the ledger comparison and the pull request.

**M0 (before M1):** record the collected count (`--collect-only -q`) of every existing file in G2. Static counts of top-level test functions on the reading tree: `test_ad791g_main_chat_thread.py` 8, `test_ad719_episodic_writes.py` 3, `test_bf813_denial_consumers.py` 21.

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1, P2-2 (route); P2-3 to P2-8 (AD-791g tests); P2-9, P2-10 (AD-719 tests); P2-11 (BF-813 tests); P2-12, P2-13 (marker and its import); P2-14 (the new file's docstring) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

- **G1.** `PY -m pytest tests/test_mention_fanout_episode_owner.py -q -n 0 -p no:randomly`.
  - **Expected (not measured):** **1 passed, 4 xfailed**. K1 passes; B1 to B4 xfail with `raises=AssertionError, strict=True`. An XPASS or any other exception is a FAIL.
  - Then run once with the marker off: `$env:MENTION_FANOUT_RUNXFAIL = "1"`, the file alone, then `Remove-Item Env:MENTION_FANOUT_RUNXFAIL`. **Expected: 4 failed, 1 passed**, each failure at its own `assert` (the last line reads `AssertionError`), none at an import, a fixture or a call.
- **G2.**
  - (1) `PY -m pytest tests/test_mention_fanout_episode_owner.py tests/test_ad791g_main_chat_thread.py tests/test_ad719_episodic_writes.py tests/test_bf813_denial_consumers.py -q -n 0 -p no:randomly`
  - (2) `PY -m pytest tests/test_ad719_chat_fanout.py tests/test_ad933a_group_episode.py tests/test_ad567a_anchor_metadata.py tests/test_bf103_episode_id_mismatch.py tests/test_ad791a_chat_threads_wiring.py tests/test_bf790_denial_is_not_silence.py tests/test_callsign_routing.py tests/test_bf791_bf792_bypass_egress.py -q -n 0 -p no:randomly`. These are the fan-out's other drivers, the group path, the real `build_episode`'s direct tests, the sovereign-id tests, and the source scans that list `routers/chat.py`; none reads the changed lines (section 11).
  - (3) `PY -P scripts/check_architecture_principles.py --check`
  - **Expected:** the new file has 5 passed; every other file has 0 failed and collected counts equal to M0; the check is clean. `architecture-baseline.yaml` has no `srp-size` row for `routers/chat.py` (its only `chat` key is `probos.routers.chat::_run_selfmod`, `unowned-task`, `:1126`) and no `layer-import` rows; `routers/memory_graph.py:14` already imports `probos.cognitive.episodic` at module level.
- **G3 (M3).** `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
  - **Expected (not measured):** no AD or BF number moves. The report's git-log row changes, and the skipped-line numbers shift by the lines each entry adds.
  - **Any changed row of an AD or BF number is a hard stop for the Architect.**

**Final gate (the orchestrator's, once, after the Diff Reviewer's findings are repaired and the reviewed tree is committed locally):** the mutation rows of section 9, then `PY scripts/run_test_gate.py --label mention-fanout-episode-owner --receipt logs/gates/mention-fanout-episode-owner.receipt.json`.

**Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing new case at G2, or any existing test failing, goes back to the Architect.

## 5. Commit messages

Every message ends its body with the paragraph `Refs #1794.`. Any trailer paragraph the committing agent adds comes after it and is not part of the body. No subject starts with, or contains, an `AD-` or `BF-` token. No message names a crew member, a thread or a live figure.

- **Contract commit (the orchestrator's):** `Mention fan-out episode owner (#1794): contract for building the @-mention reply episode in the route, owned by the replying agent`
- **M1:** `Mention fan-out episode owner M1: tests for the @-mention reply episode owned by the agent, holding the reply and the chat frame, xfail until built (#1794)`
- **M2:** `Mention fan-out episode owner M2: the route builds the reply episode itself, owned by the agent's sovereign id, and three tests that forced or faked the adapter branch say why (#1794)`
- **M3:** `Mention fan-out episode owner M3: trackers and ledger (#1794)`

The slice completes the bug, but **no message uses a closing keyword in any case or form**: close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved. The pull-request body carries the closing line (D8), and the orchestrator verifies closure. Two scans over the slice's range must print nothing:
- `git log --format=%B 5275d008..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B 5275d008..HEAD | rg -n -i "\b(clos[e][sd]?|fix(e[sd])?|resolv[e][sd]?)\b"`

## 6. Tests

**New file `tests/test_mention_fanout_episode_owner.py` (5 cases).**

Fixtures:
- a real `EpisodicMemory(db_path=tmp_path / "episodes.db", max_episodes=100, relevance_threshold=0.3)`, started and stopped by the fixture, as at `tests/test_ad1293_turn_record_reaches_episode.py:150-159`;
- a real `DreamAdapter` built with keyword arguments: `None` for every service, `pools={}`, a no-op emitter, and the same identity double as the runtime. Its `build_episode` is the production function, so on the base each case reaches the defect;
- a real `CallsignRegistry` bound to an agent-registry double, with three callsigns (pattern of `test_ad791g_main_chat_thread.py:43-71`);
- a real `ChatThreadStore(tmp_path / "chat_threads.db")`;
- an identity double whose `get_by_slot` returns `SimpleNamespace(agent_uuid=...)` for two slots and `None` for the third (the only call `resolve_sovereign_id_from_slot` makes, `episodic.py:482-484`);
- a bus double that answers each target with its own reply, refuses one target (`IntentAuthorizationDenied`) or fails one (`RuntimeError`), as at `test_bf813_denial_consumers.py:325-343`;
- the runtime: a `MagicMock` whose every attribute the fan-out reads is set to one of the above.

The driver is the route handler `chat(...)`, called as AD-791g's tests call it. The HTTP layer is not in question. Every case has its own temporary databases; nothing is shared.

| Case | Kind | Asserts |
|---|---|---|
| B1 `test_each_reply_is_stored_as_its_agents_own_episode` | built | three genuine replies (premise); the `multi_agent_chat` episodes' `agent_ids` are exactly `[[sov-test-alpha-0001], [sov-test-bravo-0002], [<TestCharlie's slot>]]`: sovereign where certificated, slot where not |
| B2 `test_each_episode_holds_the_reply_and_the_chat_frame` | built | per owner: `user_input == "@<callsign> status report please"`; `reflection == "<callsign> said: <reply>"`; the only outcome's `response` is the reply; frame `("chat", "at_mention_fanout")`; `chat_thread_id == MAIN_CHAT_THREAD_ID`; `participants == ["captain", <callsign>]` |
| B3 `test_the_owner_recalls_its_reply_by_its_own_words` (**the cross-seam case**) | built | for each agent, `memory.recall_for_agent(<owner>, <reply text>, k=5)` returns exactly one `multi_agent_chat` episode, and its reflection holds that reply |
| B4 `test_the_reflection_keeps_600_characters_of_a_long_reply` | built | a 700-character reply: `reflection == "TestAlpha said: " + reply[:600]`; the outcome's `response == reply[:500]` |
| K1 `test_a_refused_or_failed_reply_stores_no_episode` | control (BF-813's negative) | statuses `{"TestAlpha": "", "TestBravo": "refused", "TestCharlie": "delivery_failed"}`; the store holds exactly one episode of any kind, `user_input == "@TestAlpha status report please"`; passes on the base and after |

**How each built case fails on the base** (expected): the base stores three episodes with `source` direct, so the `multi_agent_chat` filter returns none.
- B1 fails at its owner assert (`[] != [...]`).
- B2 and B4 fail at `sorted(by_owner) == ...` / `_owner("TestAlpha") in by_owner`.
- B3 fails at its list assert, because the base's episodes have no owner and recall's ownership check (`episodic.py:3992-3993`) drops them.

**The existing files.** The AD-791g file keeps its 8 cases, and Test 4 changes its assertions (D6). The AD-719 file keeps 3, and its fixture no longer forces the adapter off. The BF-813 file keeps 21, and its fan-out runtime pins `identity_registry = None`.

## 7. The contract

Labels restart in the slice. SEARCH text is LF; the working copies are CRLF (the apply tool matches on LF). **Every SEARCH below occurs exactly once in its file on `2b4b783a`, `c408860b` and `5275d008` (measured, section 15), starts at a line start and is ASCII.** Each anchor line was checked with Grep (section 11). The non-ASCII lines of the edited files were enumerated (`chat.py`: `:341`, `:395`, `:413` are near the edits and are outside every SEARCH; `test_ad791g_main_chat_thread.py`: `:75`, `:268`, `:271`, `:275`, `:294`, `:311` are outside every SEARCH; `test_ad719_episodic_writes.py`: `:49`, `:124` are outside; `test_bf813_denial_consumers.py`: none). The oracle must run the full-block check.

No two SEARCHes overlap. The blocks of one file are applied in label order. **A label line names its file by full path in backticks.**

### 7.1 Slice S1 (the @-mention fan-out builds its reply episode itself)

#### S1 M1

**N1-1.** New file `tests/test_mention_fanout_episode_owner.py` (5 cases). It imports only modules that exist on the base. Every built case fails on the base at an `assert`: no index before the assert that guards it, and no patch of a missing name.

```python
"""An @-mention fan-out reply is stored as the replying agent's own episode (#1794).

``routers/chat.py`` stores one episode per genuine reply of an @-mention fan-out. With a ``DreamAdapter`` on the
runtime (``startup/finalize.py`` builds one) the route used to call ``DreamAdapter.build_episode`` with a
``response`` and an ``agent_ids`` key; that function reads only ``dag``, ``results`` and ``reflection``, so the
stored episode had no owner, none of the reply, the ``direct`` source and a ``dag`` frame, and the agent's own
recall could not return it.

These cases drive the route with a REAL ``DreamAdapter``, a REAL ``EpisodicMemory`` on a temporary path and an
identity registry double that maps slot ids to sovereign ids, and read back what was stored; one case recalls each
episode as its owner, by the words of the reply.

Synthetic fixtures only. The cases marked ``built`` fail on the base at their own assert and pass once the route
builds the Episode itself; ``MENTION_FANOUT_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.crew_profile import CallsignRegistry
from probos.dream_adapter import DreamAdapter
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied
from probos.routers.chat import chat
from probos.threads import MAIN_CHAT_THREAD_ID, ChatThreadStore

built = (
    (lambda func: func)
    if os.environ.get("MENTION_FANOUT_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)

_CAPTAIN_TEXT = "status report please"
_LONG_REPLY = "y" * 700

# callsign -> (agent type, slot id, sovereign id or "" where the slot has no certificate, reply text)
_CREW: dict[str, tuple[str, str, str, str]] = {
    "TestAlpha": (
        "test_alpha_officer", "test_alpha_officer_test_0_aaaa0001", "sov-test-alpha-0001",
        "The coolant pump bearing reads warm on loop two.",
    ),
    "TestBravo": (
        "test_bravo_officer", "test_bravo_officer_test_0_bbbb0002", "sov-test-bravo-0002",
        "Forward array sweep returns nominal echoes.",
    ),
    "TestCharlie": (
        "test_charlie_officer", "test_charlie_officer_test_0_cccc0003", "",
        "Shuttle bay doors cycle within tolerance.",
    ),
}


def _slot(callsign: str) -> str:
    return _CREW[callsign][1]


def _owner(callsign: str) -> str:
    """The id the episode must be owned by: the sovereign id, or the slot id where the slot has no certificate."""
    _type, slot, sovereign, _reply_text = _CREW[callsign]
    return sovereign or slot


def _reply(callsign: str) -> str:
    return _CREW[callsign][3]


class _Agent:
    def __init__(self, agent_id: str) -> None:
        self.id = agent_id
        self.is_alive = True


class _AgentRegistry:
    """What ``CallsignRegistry.resolve`` asks of the agent registry: the live agents of a type."""

    def __init__(self, by_type: dict[str, list[_Agent]]) -> None:
        self._by_type = by_type

    def get_by_pool(self, agent_type: str) -> list[_Agent]:
        return self._by_type.get(agent_type, [])


class _IdentityRegistry:
    """What ``resolve_sovereign_id_from_slot`` asks of the identity registry: a slot's certificate, or None."""

    def __init__(self) -> None:
        self._sovereign_by_slot = {slot: sov for _t, slot, sov, _r in _CREW.values() if sov}

    def get_by_slot(self, slot_id: str) -> Any:
        sovereign = self._sovereign_by_slot.get(slot_id)
        return SimpleNamespace(agent_uuid=sovereign) if sovereign else None


class _Bus:
    """Answers each target with its own reply; refuses or fails the targets it is told to."""

    def __init__(self, *, deny: str = "", fail: str = "", replies: dict[str, str] | None = None) -> None:
        self._deny = deny
        self._fail = fail
        self._reply_by_slot = {slot: text for _t, slot, _s, text in _CREW.values()}
        self._reply_by_slot.update(replies or {})

    async def send(self, intent: Any, *, raise_on_denial: bool = False, **_kw: Any) -> Any:
        target = str(getattr(intent, "target_agent_id", ""))
        if target == self._deny and raise_on_denial:
            raise IntentAuthorizationDenied(intent_name="direct_message", reason="test-policy", entry_point="send")
        if target == self._fail:
            raise RuntimeError("test transport failure")
        return SimpleNamespace(result=self._reply_by_slot[target], error=None)


def _callsign_registry() -> CallsignRegistry:
    registry = CallsignRegistry()
    by_type: dict[str, list[_Agent]] = {}
    for callsign, (agent_type, slot, _sovereign, _reply_text) in _CREW.items():
        registry.set_callsign(agent_type, callsign)
        by_type[agent_type] = [_Agent(slot)]
    registry.bind_registry(_AgentRegistry(by_type))
    return registry


@pytest.fixture
async def memory(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "episodes.db", max_episodes=100, relevance_threshold=0.3)
    await mem.start()
    yield mem
    await mem.stop()


def _runtime(tmp_path: Any, memory: EpisodicMemory, bus: _Bus) -> Any:
    """Every attribute the fan-out reads, set to a real object or a double above; a REAL ``DreamAdapter``."""
    identity = _IdentityRegistry()
    runtime = MagicMock()
    runtime.callsign_registry = _callsign_registry()
    runtime.intent_bus = bus
    runtime.episodic_memory = memory
    runtime.identity_registry = identity
    runtime.chat_thread_store = ChatThreadStore(tmp_path / "chat_threads.db")
    runtime.dream_adapter = DreamAdapter(
        dream_scheduler=None,
        emergent_detector=None,
        episodic_memory=memory,
        knowledge_store=None,
        hebbian_router=None,
        trust_network=None,
        event_emitter=lambda *args, **kwargs: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=None,
        event_log=None,
        config=None,
        pools={},
        identity_registry=identity,
    )
    return runtime


async def _fan_out(runtime: Any) -> dict[str, Any]:
    request = MagicMock()
    request.message = " ".join(f"@{callsign}" for callsign in _CREW) + " " + _CAPTAIN_TEXT
    request.history = []
    request.attachment_ids = []
    request.thread_id = None
    return await chat(request, runtime=runtime, track_task=Mock(), broadcast=Mock(), pending_designs={})


async def _fanout_episodes(memory: EpisodicMemory) -> list[Any]:
    return [ep for ep in await memory.recent(k=50) if str(ep.source) == "multi_agent_chat"]


async def _fanout_episodes_by_owner(memory: EpisodicMemory) -> dict[str, Any]:
    return {ep.agent_ids[0]: ep for ep in await _fanout_episodes(memory) if len(ep.agent_ids) == 1}


@built
async def test_each_reply_is_stored_as_its_agents_own_episode(tmp_path, memory) -> None:
    """One episode per genuine reply, owned by the agent's sovereign id (its slot id where it has none)."""
    response = await _fan_out(_runtime(tmp_path, memory, _Bus()))
    assert [r["status"] for r in response["per_agent_replies"]] == ["", "", ""], "premise: three genuine replies"

    episodes = await _fanout_episodes(memory)
    assert sorted(ep.agent_ids for ep in episodes) == sorted([_owner(callsign)] for callsign in _CREW)


@built
async def test_each_episode_holds_the_reply_and_the_chat_frame(tmp_path, memory) -> None:
    await _fan_out(_runtime(tmp_path, memory, _Bus()))

    by_owner = await _fanout_episodes_by_owner(memory)
    assert sorted(by_owner) == sorted(_owner(callsign) for callsign in _CREW)
    for callsign in _CREW:
        episode = by_owner[_owner(callsign)]
        assert episode.user_input == f"@{callsign} {_CAPTAIN_TEXT}"
        assert episode.reflection == f"{callsign} said: {_reply(callsign)}"
        assert [outcome.get("response") for outcome in episode.outcomes] == [_reply(callsign)]
        assert episode.anchors is not None
        assert (episode.anchors.channel, episode.anchors.trigger_type) == ("chat", "at_mention_fanout")
        assert episode.anchors.chat_thread_id == MAIN_CHAT_THREAD_ID
        assert episode.anchors.participants == ["captain", callsign]


@built
async def test_the_owner_recalls_its_reply_by_its_own_words(tmp_path, memory) -> None:
    """The seam the defect broke: route, store, then the owner's own recall, queried by the reply's words."""
    await _fan_out(_runtime(tmp_path, memory, _Bus()))

    for callsign in _CREW:
        recalled = await memory.recall_for_agent(_owner(callsign), _reply(callsign), k=5)
        assert [ep.reflection for ep in recalled if str(ep.source) == "multi_agent_chat"] == [
            f"{callsign} said: {_reply(callsign)}"
        ]


@built
async def test_the_reflection_keeps_600_characters_of_a_long_reply(tmp_path, memory) -> None:
    """The reflection keeps the group fan-out's shipped cap; the outcome keeps 500, as the group fan-out's does."""
    bus = _Bus(replies={_slot("TestAlpha"): _LONG_REPLY})
    await _fan_out(_runtime(tmp_path, memory, bus))

    by_owner = await _fanout_episodes_by_owner(memory)
    assert _owner("TestAlpha") in by_owner
    episode = by_owner[_owner("TestAlpha")]
    assert episode.reflection == f"TestAlpha said: {_LONG_REPLY[:600]}"
    assert [outcome.get("response") for outcome in episode.outcomes] == [_LONG_REPLY[:500]]


async def test_a_refused_or_failed_reply_stores_no_episode(tmp_path, memory) -> None:
    """The genuine-turn gate is kept: a refused or failed recipient is never stored as having spoken (control)."""
    bus = _Bus(deny=_slot("TestBravo"), fail=_slot("TestCharlie"))
    response = await _fan_out(_runtime(tmp_path, memory, bus))

    statuses = {r["callsign"]: r["status"] for r in response["per_agent_replies"]}
    assert statuses == {"TestAlpha": "", "TestBravo": "refused", "TestCharlie": "delivery_failed"}
    assert [ep.user_input for ep in await memory.recent(k=50)] == [f"@TestAlpha {_CAPTAIN_TEXT}"]
```

#### S1 M2

**P2-1** (`src/probos/routers/chat.py`: the reflection cap, a module constant).
SEARCH:
```
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])
```
REPLACE:
```
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# #1794: how much of an agent's own reply its @-mention fan-out episode
# indexes (the reflection). 600 is the cap the group fan-out applies as
# shipped (memory.group_reflection_max_chars with enrichment enabled in
# config/system.yaml), so a reply is indexed to the same length whichever
# fan-out stored it.
_MENTION_REFLECTION_MAX_CHARS = 600
```

**P2-2** (`src/probos/routers/chat.py`: the fan-out's episode, one construction, no branch; the replace and the store that follow (`:395-409`) are unchanged).
SEARCH:
```
                t_end_fanout = time.monotonic()
                dream_adapter = getattr(runtime, "dream_adapter", None)
                for reply in per_agent_replies:
                    if not _is_genuine_agent_turn(reply):
                        continue
                    try:
                        episode_input = f"@{reply.callsign} {remaining_message}"
                        if dream_adapter is not None:
                            episode = dream_adapter.build_episode(
                                episode_input,
                                {"response": reply.text, "agent_ids": [reply.agent_id]},
                                t_start_fanout,
                                t_end_fanout,
                            )
                        else:
                            from probos.types import AnchorFrame, Episode
                            episode = Episode(
                                timestamp=time.time(),
                                user_input=episode_input,
                                dag_summary={},
                                outcomes=[],
                                agent_ids=[reply.agent_id],
                                duration_ms=(t_end_fanout - t_start_fanout) * 1000,
                                source="multi_agent_chat",  # AD-719 distinct tag
                                anchors=AnchorFrame(
                                    channel="chat",
                                    trigger_type="at_mention_fanout",
                                ),
                            )
                        # AD-791g / AD-933a TRAP: anchor the episode to the
                        # shared main-chat thread AFTER the if/else so BOTH
                        # branches are reached. ``dream_adapter.build_episode``
                        # returns a channel="dag" AnchorFrame that does NOT set
                        # chat_thread_id, so augmenting only the else-branch
                        # AnchorFrame would silently drop the id in production
                        # (where a dream_adapter exists). Episode + AnchorFrame
                        # are BOTH frozen dataclasses, so we rebuild via
                        # ``dataclasses.replace`` rather than assign in place.
```
REPLACE:
```
                t_end_fanout = time.monotonic()
                # #1794: ONE Episode construction, no adapter branch.
                # DreamAdapter.build_episode reads only the dag, results and
                # reflection keys, so on a started vessel (which has an
                # adapter) the old branch stored an episode with no owner, a
                # dag frame and none of the reply. Same shape as the group
                # fan-out (AD-933a, routers/thread_fanout.py).
                from probos.cognitive.episodic import resolve_sovereign_id_from_slot
                from probos.types import AnchorFrame, Episode
                for reply in per_agent_replies:
                    if not _is_genuine_agent_turn(reply):
                        continue
                    try:
                        episode_input = f"@{reply.callsign} {remaining_message}"
                        # The owner is the agent's sovereign id where its slot
                        # has a certificate, the slot id otherwise.
                        owner_id = resolve_sovereign_id_from_slot(
                            reply.agent_id, runtime.identity_registry,
                        )
                        speaker = reply.callsign or owner_id
                        episode = Episode(
                            timestamp=time.time(),
                            user_input=episode_input,
                            dag_summary={},
                            outcomes=[{
                                "intent": "direct_message",
                                "success": True,
                                "response": reply.text[:500],
                                "callsign": reply.callsign,
                                "source": "multi_agent_chat",
                            }],
                            agent_ids=[owner_id],
                            duration_ms=(t_end_fanout - t_start_fanout) * 1000,
                            # AD-977 parity: index the agent's own reply, so
                            # its episode is findable by its words, not only
                            # by the Captain's.
                            reflection=f"{speaker} said: {reply.text[:_MENTION_REFLECTION_MAX_CHARS]}",
                            source="multi_agent_chat",  # AD-719 distinct tag
                            anchors=AnchorFrame(
                                channel="chat",
                                trigger_type="at_mention_fanout",
                                participants=["captain", speaker],
                            ),
                        )
                        # AD-791g: anchor the episode to the shared main-chat
                        # thread. Episode + AnchorFrame are BOTH frozen
                        # dataclasses, so we rebuild via
                        # ``dataclasses.replace`` rather than assign in place.
```

**P2-3** (`tests/test_ad791g_main_chat_thread.py`: the fake adapter counts its calls, and its docstring says what it is).
SEARCH:
```
    shape of the real ``dream_adapter.build_episode`` (dream_adapter.py:410).
    The AD-933a regression guard: the fan-out must post-mutate the anchor
    AFTER the if/else so this branch's id is set too.
    """

    def build_episode(
        self,
        text: str,
        execution_result: dict,
        t_start: float,
        t_end: float,
    ):
        from probos.types import AnchorFrame, Episode

        return Episode(
```
REPLACE:
```
    shape of the real ``dream_adapter.build_episode`` (dream_adapter.py:410),
    except that it copies ``agent_ids``, which the real one never reads.
    #1794: the fan-out no longer calls it (one Episode construction, no
    branch), so it counts its calls and Test 4 asserts there are none.
    """

    calls = 0

    def build_episode(
        self,
        text: str,
        execution_result: dict,
        t_start: float,
        t_end: float,
    ):
        from probos.types import AnchorFrame, Episode

        self.calls += 1
        return Episode(
```

**P2-4** (`tests/test_ad791g_main_chat_thread.py`: the fan-out factory; the adapter stays `None` and the identity registry is pinned).
SEARCH:
```
    CallsignRegistry; AsyncMock intent_bus + episodic store; dream_adapter
    forced to None so the else-branch (real Episode) runs deterministically.
    """
    runtime = MagicMock()
    runtime.callsign_registry = _make_callsign_registry()
    runtime.intent_bus.send = AsyncMock(
        return_value=SimpleNamespace(result=reply_text, error=None),
    )
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock()
    runtime.dream_adapter = None
```
REPLACE:
```
    CallsignRegistry; AsyncMock intent_bus + episodic store. #1794: the route
    no longer reads dream_adapter (one Episode construction), so it stays
    None only to keep this runtime's shape. identity_registry is None because
    the route now resolves each owner through it, and a MagicMock registry
    hands back a mock certificate: with None the slot id is the owner.
    """
    runtime = MagicMock()
    runtime.callsign_registry = _make_callsign_registry()
    runtime.intent_bus.send = AsyncMock(
        return_value=SimpleNamespace(result=reply_text, error=None),
    )
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock()
    runtime.dream_adapter = None
    runtime.identity_registry = None
```

**P2-5** (`tests/test_ad791g_main_chat_thread.py`: Test 4's header; line `:268` before it is unchanged).
SEARCH:
```
# else-branch (dream_adapter=None) AND the build_episode branch (fake
# dream_adapter returns channel="dag", no chat_thread_id).
```
REPLACE:
```
# runtime without an adapter AND with one. #1794: the route no longer
# calls build_episode, so both store the chat Episode the route builds.
```

**P2-6** (`tests/test_ad791g_main_chat_thread.py`: Test 4's second-half comment; lines `:294-295` after it are unchanged and continue the sentence).
SEARCH:
```
    # build_episode branch: fake dream_adapter returns a channel="dag"
    # AnchorFrame with NO chat_thread_id. The post-mutation AFTER the
```
REPLACE:
```
    # An adapter present (the production shape). History: the route once
    # called its build_episode, whose AnchorFrame had NO chat_thread_id, so
    # the post-mutation AFTER the
```

**P2-7** (`tests/test_ad791g_main_chat_thread.py`: Test 4 asserts the adapter is never called; the comment that pinned the defect is replaced; line `:311` after it is unchanged and continues the sentence).
SEARCH:
```
    stored2 = [c.args[0] for c in runtime2.episodic_memory.store.call_args_list]
    assert len(stored2) == 2
    for ep in stored2:
        assert ep.anchors is not None
        assert ep.anchors.chat_thread_id == MAIN_CHAT_THREAD_ID
        # Proves the episode came from build_episode (dag-shaped), so the
```
REPLACE:
```
    stored2 = [c.args[0] for c in runtime2.episodic_memory.store.call_args_list]
    assert len(stored2) == 2
    # #1794: the adapter is present and is never called.
    assert runtime2.dream_adapter.calls == 0
    for ep in stored2:
        assert ep.anchors is not None
        assert ep.anchors.chat_thread_id == MAIN_CHAT_THREAD_ID
        # #1794: this asserted channel == "dag" until the route stopped
        # calling build_episode, so it pinned the defect (an episode with no
        # owner, a dag frame and none of the reply). A chat frame with the
        # adapter present proves the anchor's
```

**P2-8** (`tests/test_ad791g_main_chat_thread.py`: the assertion that pinned the defect).
SEARCH:
```
        assert ep.anchors.channel == "dag"
```
REPLACE:
```
        assert ep.anchors.channel == "chat"
```

**P2-9** (`tests/test_ad719_episodic_writes.py`: the fixture no longer forces the adapter off).
SEARCH:
```
    # Force the dream_adapter off so the loop takes the explicit Episode
    # construction branch (deterministic source tag).
    rt.dream_adapter = None
```
REPLACE:
```
    # #1794: the runtime's dream_adapter is left as start() built it. The
    # route no longer reads it (one Episode construction, no branch), so
    # these cases run the production shape; forcing it to None used to hide
    # the ownerless episode that the adapter branch stored.
```

**P2-10** (`tests/test_ad719_episodic_writes.py`: the comment that named the forced branch).
SEARCH:
```
        # dream_adapter is forced None in the fixture so this path constructs
        # Episode directly with the AD-719 distinct source tag.
```
REPLACE:
```
        # #1794: the route constructs the Episode itself with the AD-719
        # distinct source tag, whether or not the runtime has an adapter.
```

**P2-11** (`tests/test_bf813_denial_consumers.py`: the fan-out runtime pins the identity registry; without it four cases compare mock owners).
SEARCH:
```
    rt.episodic_memory = _Episodic()
    rt.dream_adapter = None
```
REPLACE:
```
    rt.episodic_memory = _Episodic()
    # #1794: the route no longer reads dream_adapter; it stays None only to
    # keep this runtime's shape. The route now resolves each episode's owner
    # through identity_registry, and a MagicMock registry is truthy and
    # returns a mock certificate, so it is None here: the slot id is then the
    # owner, which is what _episode_agents compares.
    rt.dream_adapter = None
    rt.identity_registry = None
```

**P2-12** (`tests/test_mention_fanout_episode_owner.py`: the marker, after P2-1 to P2-11).
SEARCH:
```
built = (
    (lambda func: func)
    if os.environ.get("MENTION_FANOUT_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)
```
REPLACE:
```
def built(func):
    """The built cases pass; the marker no longer fails them."""
    return func
```

**P2-13** (`tests/test_mention_fanout_episode_owner.py`: the import that only the marker used).
SEARCH:
```
import os
from types import SimpleNamespace
```
REPLACE:
```
from types import SimpleNamespace
```

**P2-14** (`tests/test_mention_fanout_episode_owner.py`: the docstring's last paragraph, which named the switch that P2-12 removes).
SEARCH:
```
Synthetic fixtures only. The cases marked ``built`` fail on the base at their own assert and pass once the route
builds the Episode itself; ``MENTION_FANOUT_RUNXFAIL=1`` runs them as plain cases.
```
REPLACE:
```
Synthetic fixtures only. The cases marked ``built`` failed on the base at their own assert and pass now that the
route builds the Episode itself; the marker is a no-op, kept as documentation of which cases the base fails.
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it. Replace `DATE` with M3's date. The entry is 4 lines (heading, two bullets, blank). The heading starts with a word.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**An @-mention fan-out reply is stored as the replying agent's own episode (DATE), #1794 -- the route builds the episode itself, owned by the agent's sovereign id, with the reply, the chat frame and the main-chat thread id.**
- **Base.** For each genuine reply of an @-mention fan-out, `routers/chat.py` called `DreamAdapter.build_episode` whenever the runtime had an adapter (a started vessel builds one), with a `response` and an `agent_ids` key that the function never reads: the stored episode had no owner, none of the reply, the `direct` source and the `dag` frame, so a recall scoped to the agent could not return it. Only the branch without an adapter wrote the intended episode, and the tests either forced that branch or faked the adapter with a `build_episode` that copied the key.
- **Change.** One `Episode` construction, no branch, as the group-chat fan-out has built its episode since it met the same trap: owner `resolve_sovereign_id_from_slot(<slot>, runtime.identity_registry)` (the slot id where the slot has no certificate), the reply in `outcomes` (500 characters) and in `reflection` as `<callsign> said: <reply>` (600 characters, the group fan-out's shipped cap), source `multi_agent_chat`, frame `chat` / `at_mention_fanout` with participants `captain` and the callsign, then the main-chat thread id as before. A refused or failed reply still stores nothing. Episodes already stored without an owner are not rewritten: they hold no reply. A new test file drives the route with a real adapter, a real episodic store and a registry double that maps slots to sovereign ids, and recalls each episode as its owner by the reply's words; three existing test files that forced or faked the adapter branch say why inline. Contract `prompts/mention-fanout-episode-owner.md`. Refs #1794.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading of the entry that follows this period's entries (once on `c408860b`, line 1788, and on `5275d008`, line 1796). This slice's entry is inserted before it, after the entries of the merged batch. If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date. The heading names no AD or BF number.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### The @-mention fan-out builds its reply episode itself, owned by the agent (DATE, #1794)

- *Scope.* `routers/chat.py` (one module constant; the fan-out's episode construction: the adapter branch deleted, one `Episode` built directly), one new test file, three existing test files updated with inline reasons (`test_ad791g_main_chat_thread.py`, `test_ad719_episodic_writes.py`, `test_bf813_denial_consumers.py`). Contract `prompts/mention-fanout-episode-owner.md`.
- *G1 (the shape).* One construction with no branch, so the two-branch trap the group-chat fan-out met cannot recur here. Rejected: a helper shared by both fan-outs (it widens the change into the group path's tested construction; deferred); teaching `DreamAdapter.build_episode` a chat shape (a second input format for a builder whose other callers pass a plan); handing `build_episode` a plan-shaped dict (it still writes the `dag` frame and the `direct` source).
- *G2 (the owner).* The agent's sovereign id through `resolve_sovereign_id_from_slot` (the slot id where the slot has no certificate); a test recalls the episode by that id. The group-chat fan-out still stores the raw slot id; not changed here.
- *G3 (the text and the frame).* `reflection = "<callsign> said: <reply[:600]>"`, the group fan-out's shipped cap as a module constant rather than its `group_` config key; the outcome's `response` keeps 500 characters, as the group fan-out's does; participants are `captain` and the callsign (the frame's field holds callsigns).
- *G4 (stored episodes).* No backfill: an ownerless fan-out episode holds the Captain's words but not the reply, so an owner added later would give the agent a memory of a question with no answer. The count on a copy of a vessel's data goes to the Architect and is not published.
- *Residual.* L1 to L11 of the contract. *Reversal.* Revert the three commits of the slice, M3 then M2 then M1; episodes stored meanwhile stay valid (owned, with the reply).

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3 (section 4). No AD or BF number moves. The roadmap Bug Tracker is not edited (L10).

## 8. What this does NOT change

- **Source:**
  - `DreamAdapter.build_episode` (`dream_adapter.py:347-423`) and its two other callers (`runtime.py:6150`, `experience/renderer.py:486`);
  - the group-chat fan-out (`routers/thread_fanout.py:1049-1150`), including its raw `agent_ids` (L2);
  - the transcript append and the genuine-turn predicate (`chat.py:319-345`);
  - the thread-id replace and the store, with its log-and-degrade arm (`chat.py:395-415`);
  - the single-mention path (`chat.py:426+`) and the vision branch (`:756-805`);
  - `resolve_sovereign_id_from_slot`, the start-up migration that rewrites slot ids (`episodic.py:488+`, `startup/cognitive_services.py:418-431`);
  - `EpisodicMemory.store` and its gates;
  - `AnchorFrame` and `Episode`.
- **Config:** no key, no model, `config/system.yaml` untouched.
- **All:** `ui/`; the commercial overlay (OSS only; no dependency; no schema change); every tracker except `PROGRESS.md`, `DECISIONS.md` and the AD ledger pair; the roadmap Bug Tracker table.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

**Not run by the Architect.** Uniqueness of each new line was reasoned from P2-2's REPLACE and Grep of `chat.py` on the base (section 11): `channel="chat",`, `trigger_type="at_mention_fanout",` and `source="multi_agent_chat",  # AD-719 distinct tag` occur once there today and are replaced, and `"source": "multi_agent_chat",` (without the comment) is **not** unique (`:182`, `:334`), so no row uses it. The Killed-by cells were expected; the oracle measured all 15 rows (section 15) and corrected the cells of rows 6 and 11.

The oracle's campaign: replace each row's line whole in the built file, run the new file plus the named existing files, then restore the file and check its blob. **This table is the campaign of record only for a tree whose files equal the blobs the blocks give on `2b4b783a`** (the blob ids are in section 15). A Builder whose files match does not repeat it; if a file differs, the rows naming it are rerun.

| # | File | Line (stripped) | Mutate to | Killed by (measured, section 15) |
|---|---|---|---|---|
| 1 | `src/probos/routers/chat.py` | `agent_ids=[owner_id],` | `agent_ids=[reply.agent_id],` | B1, B2, B3, B4 |
| 2 | same | `reply.agent_id, runtime.identity_registry,` | `reply.agent_id, None,` | B1, B2, B3, B4 |
| 3 | same | `reflection=f"{speaker} said: {reply.text[:_MENTION_REFLECTION_MAX_CHARS]}",` | `reflection=None,` | B2, B3, B4 |
| 4 | same | `_MENTION_REFLECTION_MAX_CHARS = 600` | `_MENTION_REFLECTION_MAX_CHARS = 240` | B4 |
| 5 | same | `speaker = reply.callsign or owner_id` | `speaker = owner_id` | B2, B3, B4 |
| 6 | same | `source="multi_agent_chat",  # AD-719 distinct tag` | `source="direct",` | B1, B2, B3, B4; `test_ad719_episodic_writes.py::test_fanout_writes_one_episode_per_reply` and `::test_fanout_skips_episode_for_stub_reply` (its `test_fanout_episode_source_tag_distinct` skips instead of failing: its spy sees no `multi_agent_chat` episode) |
| 7 | same | `channel="chat",` | `channel="dag",` | B2; `test_ad791g_main_chat_thread.py::test_fanout_episode_anchored_both_branches` |
| 8 | same | `trigger_type="at_mention_fanout",` | `trigger_type="dag_execution",` | B2 |
| 9 | same | `participants=["captain", speaker],` | `participants=[],` | B2 |
| 10 | same | `"response": reply.text[:500],` | `"response": reply.text,` | B4 |
| 11 | same | `if not _is_genuine_agent_turn(reply):` | `if False:` | K1; `test_ad719_episodic_writes.py::test_fanout_skips_episode_for_stub_reply`; `test_bf813_denial_consumers.py::test_a_refused_recipient_is_not_recorded_as_having_spoken` and `::test_a_failed_delivery_is_also_kept_out_of_episodic_memory` |
| 12 | same | `chat_thread_id=MAIN_CHAT_THREAD_ID,` (unchanged line) | `chat_thread_id="",` | B2; `test_ad791g_main_chat_thread.py::test_fanout_episode_anchored_both_branches` |
| 13 | same | `episode_input = f"@{reply.callsign} {remaining_message}"` | `episode_input = remaining_message` | B2, K1 |
| 14 | `tests/test_bf813_denial_consumers.py` | block P2-11 reverted, M2's `chat.py` applied | | `test_two_allowed_recipients_are_both_recorded`, `test_a_refused_recipient_is_not_recorded_as_having_spoken`, `test_a_failed_delivery_is_also_kept_out_of_episodic_memory`, `test_an_agent_that_genuinely_says_a_placeholder_is_still_recorded` (a required edit, not a mutant) |
| 15 | `tests/test_ad791g_main_chat_thread.py` | blocks P2-7 and P2-8 reverted, M2's `chat.py` applied | | `test_fanout_episode_anchored_both_branches` at `channel == "dag"` (a required edit) |

## 10. Recorded limits

- **L1. Episodes already stored without an owner are not rewritten** (D7). The count on a copy of a vessel's data is owed under #1794's acceptance, and it goes to the Architect unpublished.
- **L2. The group-chat fan-out still stores the raw registry key** (`thread_fanout.py:1115`: `agent_ids=[reply["agent_id"]]`); this contract does not change it. The start-up migration that rewrites slot ids to sovereign ids (`migrate_episode_agent_ids`, `episodic.py:488-499`) runs at start only:
  - when the episodic store and an identity registry exist and `PROBOS_SKIP_EPISODIC_MIGRATIONS` is unset (`startup/cognitive_services.py:388-390`, `:419`);
  - and it skips its scan when `memory.schema_version_tracking` is on and the recorded version matches (`:404`, `:54-97`). The default is `False` (`config.py:886`), and Grep of `config/system.yaml` found no override.

  So "rewritten at the next start" holds only under those conditions (read, not run). A group reply stays keyed by slot until then.
- **L3. Shapley values and trust deltas are no longer attached** to these episodes. The adapter copied `_last_shapley_values`, the most recent consensus's (`dream_adapter.py:390-391`), and the trust events since `t_start` (`:394-405`), which this route passed as a `time.monotonic()` reading (`chat.py:158`). The new episode carries neither, as the branch without an adapter did. Not measured: what those fields held on the base for these episodes.
- **L4. The episodic store's per-agent gates now apply to these episodes** (read, not tested). The hourly cap of 20 per agent and the 30-minute near-duplicate check (Jaccard 0.8) both return early for an episode with no owner (`episodic.py:1374-1376`, `:3300-3301`, `:3326-3327`). On a started vessel these episodes were therefore exempt; now they count toward and are subject to both. The shadow admission check at store (`:2018`) is now handed an id; its comment says it blocks nothing.
- **L5. The reply is now in the indexed text.** The embedded document includes the reflection (`episodic.py:4433-4458`), so a reader that searches the whole store, not one agent's records, can find it, as it can a group reply. Measured by review round 1 (F3): a query by the reply's words finds the owned episode, but the Oracle's episode projection carries only `user_input` (`cognitive/oracle_service.py:989`, `:1007`), as it does for every episode. Not changed here; recorded on #1523.
- **L6. Not measured (#1794):** whether the agent's own handling of the `direct_message` intent also stores an episode of the same exchange. This slice stores exactly one fan-out episode per genuine reply, as before.
- **L7. The single-mention path is unchanged.** The fan-out runs only for two or more mentions (`chat.py:157`). The single-mention path's comment says it writes no episode (`:448-449`); that is a comment, not verified here.
- **L8. The test's identity registry is a double** whose only method is `get_by_slot`. The production `AgentIdentityRegistry.get_by_slot` has the same signature (`identity.py:787`), but the real registry is not exercised.
- **L9. The cap is a constant.** If `memory.group_reflection_max_chars` is reconfigured, the two fan-outs' caps differ.
- **L10. The roadmap Bug Tracker is not edited** (its highest row is BF-927, per #1794's numbering paragraph).
- **L11. B3 depends on the embedding the test environment has** (the cached model, or the fallback when the download guard refuses it: `tests/conftest.py:181-196`). Measured: B3 fails on the base at its own assert and passes after M2, in the oracle's environment (section 15). The similarity cut it must clear is `min(0.3, 0.25)` (`episodic.py:3959`). If it fails only there, the oracle reports it to the Architect; do not loosen it.
- **L12. The shared storage gate's near-duplicate check is owner-blind** (review rounds 1 and 2, F1). The AD-610 gate compares the words (`set(text.lower().split())`, `cognitive/similarity.py:17`) of an episode's `user_input`, `reflection` and outcome `result` with the last 50 fingerprints of every writer, whatever their owner (`cognitive/storage_gate.py:71-80`, `:109-133`), and a REJECT skips persistence (`episodic.py:2092-2103`); the shipped configuration enables it at 0.95 (`config/system.yaml:2036-2038`). Two agents' episodes of one mention fan-out differ only by the callsign, twice each (`@<callsign>` in `user_input`, `<callsign> said:` in `reflection`), so the later one is rejected when the two share about 76 distinct words or more, the question's included. The base's rows held only `@<callsign> <question>`, so a question of about 38 distinct words already lost the later rows there; distinct replies add distinct words, so the candidate keeps those (measured by the orchestrator: a question of 30 distinct words stores 3 rows on the base and one of 40 stores 1; the candidate stores 3 for the 40-word question with distinct replies). What is lost, by reader: an owner-scoped reader found nothing on the base (B3) and now finds every admitted agent's episode. An unscoped reader, `IntrospectionAgent._why` (`agents/introspect.py:625`, `recall(question, k=5)` with no agent filter, returning each match's `input`, `outcomes` and `agent_ids`), found the base's input-only rows; when sibling replies are near-identical it no longer finds the later agents' rows, though the question's words stay in the admitted episode's `user_input` (measured by the orchestrator with a three-word question and three identical replies: 55 distinct reply words store 3 rows, 95 store 1; the base stores 3). The group fan-out has the same exposure with a lower trigger, since its `user_input` is common to all agents (`routers/thread_fanout.py:1065-1067`) and the callsign appears once, in `reflection` (`:1130-1133`), through the same `store` (`:1145`). The store's own per-agent check is owner-scoped (`episodic.py:3324-3328`); the gate is not. Scoping the gate to the owner changes it for every writer: filed as #1798; not changed here.
- **L13. The dream replay now strengthens this reply's edge under the owner's sovereign id** (review round 1, F4). `_replay_episodes` writes a weight for each outcome with an `intent`, keyed by the episode's `agent_ids` (`cognitive/dreaming.py:2526-2562`). This outcome carries `intent` `direct_message` and `success` true, as the group fan-out's (`routers/thread_fanout.py:1107-1115`) and the 1:1 reply's (`cognitive/dm/reply_pipeline.py:2522-2534`) do, so the replay writes `(direct_message, <sovereign id>)`, which readers that score slot ids read as 0.0 (`mesh/department_dispatcher.py:146-148`). The key is not new: every 1:1 reply episode is owned by the agent's sovereign id, or its slot id where it has no certificate (`reply_pipeline.py:2502`, `:2556`; `cognitive/episodic.py:465-471`), and so is every post-action episode (`cognitive/cognitive_agent.py:12771-12774`). The base's ownerless episodes added no edge. Kept as is: dropping `intent` and `success` would break the shape the sibling paths share, which the dream's intent extraction (`dreaming.py:2738-2745`) and the readers of `success` named at `reply_pipeline.py:2524-2531` rely on; normalising the key at the replay or the router changes it for every sovereign-owned episode. The split between sovereign and slot keys is the class of F-491; recorded on #1523.
- **L14. A long reply is stored front-first, without the tool-failure facts** (review round 1, F2). The route renders each reply once, with any tool-failure disclosure as its tail (`routers/chat.py:284-300`). The episode keeps 500 characters in `response` and 600 in `reflection`, so a disclosure past the cut is not stored, and `failed_tool_names` / `failed_tool_call_count` stay empty (`types.py:706-715`) because `PerAgentReply` holds only the text and a status (`api_models.py:48-58`). The group fan-out's episode has the same omission; the 1:1 reply's stores the facts (`reply_pipeline.py:2503-2513`). No reader of the two fields exists beyond the store's own persistence (Grep of `src/`: `types.py`, `cognitive/episodic.py`, `cognitive/dm/reply_pipeline.py` only). The base stored none of the reply. Carrying the facts means threading them from the render to the episode for both fan-outs; not changed here. Recorded on #1523.

## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\next-read` at `c408860b`; `origin/main` `2b4b783a`)

**Run by the Architect, read-only.** I used the Grep, Read and Glob tools, plus git, `gh` and `ad_ceiling.py` through Bash. Nothing was written and no pytest was run.

```
git log c408860b -6 --format="%h %s" -> c408860b ... a67cc66c, 2b4b783a (Merge pull request #1791)
git diff --stat 2b4b783a c408860b -- src/probos/routers/chat.py tests/test_ad791g_main_chat_thread.py tests/test_ad719_episodic_writes.py tests/test_bf813_denial_consumers.py src/probos/cognitive/episodic.py src/probos/types.py -> (nothing)
git rev-parse <ref>:<path> for the header's blobs -> equal on both refs for every code file
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> CEILING AD-1359 (git, issues 1520 not truncated, prompts); NEXT AD-1360
gh issue view 1794 -> OPEN, "BF-964: an @-mention fan-out reply is stored as an ownerless episode ..."
gh issue list --state all --search "BF-963" -> #1793 "BF-963: ...", #1794
git log --all -E --grep "^BF-96[0-9]" -> highest subject BF-961
Grep chat.py "dream_adapter|build_episode" (src/probos/routers) -> chat.py:358, :364, :365, :388, :392; thread_fanout.py:1096, :1100 (comments)
Grep src "\.build_episode\(" -> experience/renderer.py:486, runtime.py:6150, routers/chat.py:365
Grep src "at_mention_fanout|multi_agent_chat" -> chat.py:182, :334, :380, :383 only
Grep chat.py "[^\x00-\x7F]" -> :1, :47, :70, :144, :150, :151, :163, :164, :189, :218, :341, :395, :413, :444, :449, ... (none in :30-32 or :357-394)
Grep ad791g "[^\x00-\x7F]" -> :1, :8, :15, :37, :40, :75, :191-193, :213-215, :238-240, :267-271, :275, :294, :311, :315-318, ... (none in :76-90, :115-125, :269-270 except :271, :292-293, :305-310, :312)
Grep ad719 "[^\x00-\x7F]" -> :49, :124; Grep bf813 -> none
Grep anchors: chat.py `^logger = logging.getLogger(__name__)` :30 (once), `router = APIRouter(` :32, `t_end_fanout = time.monotonic()` :357 (once), `if not _is_genuine_agent_turn(reply):` :360 (once; :325 is `_reply`); ad791g :76, :81, :116, :125/:277 (`runtime.dream_adapter = None` twice: the P2-4 SEARCH starts at the unique :115), :269-270, :292-293, :305, :310, :312 (each once); ad719 :37-39, :127-128 (once); bf813 `rt.episodic_memory = _Episodic()` :388 and `rt.dream_adapter = None` :389 (once each); PROGRESS `^# ProbOS Progress` count 1; DECISIONS anchor heading :1788 (once)
Glob tests/test_mention_fanout*, prompts/mention-fanout*, prompts/bf-964* -> none
```

**Facts read (path:line on `c408860b`).**
- `routers/chat.py`: `:6` (`import dataclasses`, still used by `:402-404`), `:30-32`, `:148-158` (the `>= 2` gate, `t_start_fanout` monotonic), `:169-193` (`MAIN_CHAT_THREAD_ID` imported under the store guard; reused under the same guard at `:231`, `:423`), `:199-299` (`_send_one`: refused `:237-264`, delivery failed `:265-276`, genuine `:277-299`), `:319-321`, `:347-415`, `:756-799` (vision precedent; `:796` sets `chat_thread_id` in the constructor).
- `dream_adapter.py:69-119` (keyword-only constructor; stores its arguments), `:347-423`.
- `routers/thread_fanout.py:1049-1057`, `:1095-1150`.
- `cognitive/episodic.py`:
  - `:474-485` (resolve), `:488-499` (migration), `:1374-1376`, `:1380-1404`;
  - `:2009-2152` (store: the shadow check `:2018`, gates `:2092-2152`), `:3298-3352`;
  - `:3894-4003` (sovereign recall; shard filter `:3974-3993`), `:4128-4131`, `:4221-4249` (`recent`);
  - `:4368-4385` (metadata keeps `reflection`, `user_input`, `source`, `anchors_json`), `:4433-4458`, `:4516-4590` (reconstruction).
- `types.py:501-537`, `:522` (participants: callsigns), `:666-705` (`Episode`), `:755-770` (`resolve_provenance`: an unknown source falls back to `DEFAULT_SOURCE_TYPE`).
- `runtime.py:1240`, `:3721`; `startup/finalize.py:6213-6214`; `startup/cognitive_services.py:54-97`, `:380-431`; `config.py:886`, `:1066-1069`; `config/system.yaml:141-142`.
- `routers/agents.py:199-202`; `routers/memory_graph.py:14`, `:105-109`; `ward_room/messages.py:324-365`; `ward_room/threads.py:578-579`.
- `identity.py:787-793`; `agent_onboarding.py:456`; `cognitive/cognitive_agent.py:11679` (`_mem_id = getattr(self, 'sovereign_id', None) or self.id`); `cognitive/participant_index.py:80-138`.
- `crew_profile.py:705-759`, `:866-904`; `dm_reply.py:816-837`, `:898-912` (body unchanged with no attachments); `mesh/pre_intent_auth.py:65-90`.
- `scripts/gen_ad_ledger.py:10-57`, `:113`, `:187-231`.
- `docs/development/architecture-baseline.yaml:1125-1131` (the only `chat` key).
- Tests:
  - `test_ad791g_main_chat_thread.py:1-129`, `:191-340`, `:411-460`;
  - `test_ad719_episodic_writes.py:1-130`;
  - `test_bf813_denial_consumers.py:96-135`, `:316-496`;
  - `test_ad1293_turn_record_reaches_episode.py:146-159`, `:520-550`;
  - `tests/conftest.py:181-196`, `:450-456`;
  - `test_ad636_llm_priority_scheduling.py:392-404`, `test_ad686b_oracle_write_semantic.py:183-209`, `test_selfmod_e2e.py:226-236`, `test_bf791_bf792_bypass_egress.py:335-364` (source scans of `chat.py`: none reads the changed lines);
  - `test_ad916_chat_file_sharing.py:440-479` (group path).

**Absence Verified (2026-11-13)**

```
CLAIM: no production code reads the source "multi_agent_chat" or the trigger "at_mention_fanout"
RUN:   Grep src/probos "at_mention_fanout|multi_agent_chat"
FOUND: routers/chat.py:182, :334 (thread-message metadata), :380, :383 (the producer)
POSITIVE CONTROL: the same search finds the producer lines
HOLDS: yes (no consumer keys on either string)

CLAIM: no other caller hands build_episode a response/agent_ids dict
RUN:   Grep src/probos "\.build_episode\("
FOUND: experience/renderer.py:486, runtime.py:6150, routers/chat.py:365
HOLDS: yes (the two others are DAG paths; not changed)

CLAIM: only three test files drive the @-mention fan-out AND touch the adapter or the stored owner
RUN:   Glob/Grep tests: files importing probos.routers.chat (23) or posting "/api/chat" (43); files naming dream_adapter (17); files naming per_agent_replies (8); Grep "episodic_memory|\.agent_ids" in the fan-out drivers
FOUND: intersection: test_ad719_episodic_writes.py, test_ad791g_main_chat_thread.py, test_bf813_denial_consumers.py. conftest.py:453 sets dream_adapter None in a fixture (inert after M2); test_ad567a/test_bf103/test_knowledge_store call the real build_episode directly; test_ad933a is the group path; test_ad916:458, test_ad914, test_ad935, test_ad948 are /api/threads; test_ad719_chat_fanout.py and test_ad791a_chat_threads_wiring.py have no agent_ids assertion on stored episodes
POSITIVE CONTROL: the search finds the three files' pins (ad791g :312, ad719 :39, bf813 :389 and :429)
HOLDS: yes

CLAIM: no source-scan test reads the lines P2-1/P2-2 change
RUN:   Grep tests 'routers[/\\.]chat(\.py)?["\']|"chat\.py"|routers" / "chat'
FOUND: conftest.py:222 (module cache), ad1195_durable_producers (SELF_MOD_* producers), ad1248_slice_b:533, ad636:396 (ttl_seconds), ad686b:194 (oracle.write_semantic), ad720d_1:194 (logger name), bf791_bf792:347 (thread-writer set), selfmod_e2e:232 (_import_approval_fn)
HOLDS: yes (none names dream_adapter, build_episode, Episode or the anchors)

CLAIM: no outcome reader keys on "session_type" (why the new outcome omits it)
RUN:   Grep src/probos '\.get\("session_type"|\["session_type"\]'
FOUND: nothing
HOLDS: yes

CLAIM: routers importing probos.cognitive is not an architecture-baseline row
RUN:   Grep architecture-baseline.yaml "memory_graph|category: layer-import"; Grep "chat"
FOUND: none; the only chat key is probos.routers.chat::_run_selfmod (unowned-task)
HOLDS: yes (expected clean check; the check itself was not run)
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.**
  - AD-933a: the group fan-out met this trap and builds its Episode directly; its comment at `thread_fanout.py:1095-1102` names the cause.
  - AD-977 and AD-986a: reflection indexing of the agent's own reply, and the 600 cap.
  - BF-103: sovereign resolution and the start-up migration, L2.
  - AD-430a: Ward Room episodes owned by `resolve_sovereign_id_from_slot`.
  - BF-813: the genuine-turn gate, kept and pinned by K1.
  - AD-791g: the main-thread anchor, kept.
  - The BF-930/932 and promotion-post contract lessons: one fence per new file, full paths in labels, cases that fail at an `assert`, expected counts, and an unused import removed in the same milestone (P2-13).
- **External:** none consulted. This is ProbOS-specific plumbing with no outside analogue. `docs/research/reference-projects.md` was not reviewed for this item (considered, deferred; today's date 2026-11-13).
- **Blind spots handled.**
  1. A `MagicMock` runtime's identity registry is truthy and hands back a mock certificate, so the fix would have turned BF-813's owner assertions red (P2-11). AD-791g's factory gets the same pin (P2-4).
  2. The thread-id replace's comment carries a non-ASCII arrow, so the replace stays and only its preceding comment is rewritten (D5).
  3. The participants field holds callsigns, not ids (D4 revises my earlier choice).
  4. An owned episode enters the per-agent rate and near-duplicate gates that an ownerless one skipped (L4).
  5. The adapter attached another consensus's Shapley values (L3).
  6. The start-up migration is conditional (L2).
  7. A test that forces the branch off cannot see the production branch: the new file uses a real adapter, and AD-719's fixture now leaves the started runtime's adapter in place.
- **What discards a correct result.** Asked separately from what makes a store fail. The correct episode is built, then it can be dropped by:
  - (a) the store's per-agent hourly cap or near-duplicate check (L4);
  - (b) the AD-610 storage gate or the AD-607h security gate, when wired (`episodic.py:2092-2142`);
  - (c) the loop's WARNING arm, for any exception, including in the owner lookup (`chat.py:410-415`);
  - (d) recall's relevance cut (`:3990-3991`), which B3 exercises once (L11).

  Recorded: L4, L5, L11.

## Batching

**One pull request and one broad gate for this slice.** It may join a batch of up to three coupled issues at the orchestrator's choice; none is coupled to it in code.

| Point | Judgement |
|---|---|
| Files | `routers/chat.py`; one new and three existing test files; the two trackers and the ledger pair |
| Order | M1, M2, M3; the tracker entries land before the anchors, after the entries of the merged batch |
| Revert | Separate commits per milestone: M3, then M2, then M1. Episodes stored meanwhile stay valid |
| Cost: Python | G1 and G2 files at `-n 0`; once, by the orchestrator: the mutation rows and `PY scripts/run_test_gate.py --label mention-fanout-episode-owner --receipt logs/gates/mention-fanout-episode-owner.receipt.json` |
| Cost: config, UI | None |

## Not in this issue: for the Captain

No step of building this slice needs a decision from the Captain, and nothing needs the vessel stopped by hand beyond the restart every merge needs. **Closing #1794 does** (item 2).

1. **Nothing to deploy, migrate or configure.** No config key, no schema change, no data migration (D7).
2. **For the orchestrator, before closure (the Captain authorises the copy: it is live data):** the D7 count, taken read-only on a **copy** of a vessel's episode data, never the live store. Count the episodes with `source` `direct`, anchors `channel` `dag` and `trigger_type` `dag_execution`, `agent_ids_json` `[]`, `dag_summary_json` `{}` and `user_input` starting `@`. Report it to the Architect, unpublished. The pull-request body carries `Closes #1794` only after that report; otherwise it says `Refs #1794`.
3. **An optional look, with no deadline.** After the next @-mention of two or more agents, ask one of them what it said in that exchange. Its own recall can now return the episode. Source of truth: the agent's reply. Not a gate.

| Data (later) | Chooses |
|---|---|
| A count in item 2 with rows that carry a reply | Revisit D7 (a backfill becomes possible) |
| Repeated identical @-mentions to one agent being deduplicated or capped | L4: whether these episodes should bypass the per-agent gates |
| A group reply missing from recall between starts | L2: resolve the owner in the group path too (option c of D2) |

## 13. Diff Reviewer: properties to verify

1. **`routers/chat.py`:**
   - one constant added after `router`;
   - the fan-out loop has exactly one `Episode(` construction and no `if`/`else` on an adapter;
   - `rg -n "dream_adapter" src/probos/routers/chat.py` prints nothing;
   - the replace (`:395-409`), the store, the WARNING arm and `_is_genuine_agent_turn` are byte-identical;
   - no `getattr` or `hasattr` is added (`runtime.identity_registry` is read directly);
   - `resolve_sovereign_id_from_slot` is imported inside the `if episodic_memory is not None:` block, before the loop.
2. **The episode's fields:**
   - `agent_ids=[owner_id]`;
   - `source="multi_agent_chat"`;
   - frame `chat` / `at_mention_fanout`;
   - `participants=["captain", speaker]`;
   - reflection `f"{speaker} said: {reply.text[:600]}"` through the constant;
   - outcome `response` `reply.text[:500]`.
3. **The new test file:**
   - ASCII; no crew name, thread id, timestamp or live count;
   - a real `DreamAdapter`, a real `EpisodicMemory` on `tmp_path`, a real `ChatThreadStore`;
   - no module-level mutable state shared across cases;
   - after M2, no `os` import, a no-op `built` and a docstring that does not name the removed switch;
   - no built case can fail anywhere but at an `assert` (read the four: no index before its guard).
4. **The three existing test files:** no test function removed; each change carries its `#1794` reason inline. `test_ad791g_main_chat_thread.py::test_fanout_episode_anchored_both_branches` asserts `channel == "chat"` and `calls == 0`.
5. **Public text:**
   - no tracker line and no commit subject holds an `AD-` or `BF-` token or a crew name;
   - no message uses a closing keyword, even to deny it (both scans of section 5 print nothing);
   - each body ends with `Refs #1794.`.
6. **The trackers:** the tracker sentences match D2 to D7 and L1. Neither claims a measured count or a live behaviour.

## 14. Acceptance criteria

1. G1, G2 and G3 pass as stated in section 4; the mutation rows and the broad gate pass.
2. Driven through the route with a real `DreamAdapter` present, each genuine reply's stored episode is owned by the agent's sovereign id (the slot id where the slot has no certificate) (B1). It holds the reply in its reflection and outcome, with the `chat` / `at_mention_fanout` frame, `participants` `["captain", <callsign>]` and the main-chat thread id (B2). The owner's own recall finds it by the reply's words (B3). The reflection keeps 600 characters (B4).
3. A refused or failed reply stores nothing (K1, and the BF-813 file).
4. The three existing test files that forced or faked the adapter branch carry their reasons inline, and none of their test functions is removed.
5. No config key is added. The AD ledger pair is the only generated artifact. No AD or BF number moves.
6. #1794 is closed by the pull request only after the D7 count has been reported; the backfill decision (D7) is recorded in `DECISIONS.md`.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-14): the oracle's measurements and the corrected cells

The orchestrator applied every block of section 7 by tool to a scratch tree (the oracle: first at the batch tip `9ac1e288`, the second parent of `5275d008` and equal to it in tree, for the first gates and mutation rows; then at `5275d008` itself, for the final blobs, G3 and a second run of the gates and mutation rows after the added pair P2-14; every SEARCH occurred exactly once, at a line start, and no pair needed an anchored copy) and measured the gates and the mutation rows. Where sections 4, 6, 9, 10 and 11 say "expected", "not measured" or "the check was not run", this section holds the measurement. A1 changed the Architect's text only here: the header (provenance, status, base blobs, tracker table, dependencies, tracker anchors); the range of the two message scans of section 5; the sentence of section 7 on where each SEARCH occurs and the prose of P3-2; two phrases of the `PROGRESS.md` entry in P3-1 (the tests "either forced that branch or faked the adapter", and "a registry double that maps slots to sovereign ids"); in section 9, the sentence on the cells, the sentence on the campaign of record, the column header and the cells of rows 6 and 11; the sentence "Expected to pass, not measured" in L11; the Order row of the Batching table; the opening and item 2 of the paragraph for the Captain; and the pair P2-14 with the three places that list the pairs of M2 (the Milestones table's M2 row, the M2 sentence of section 2 and property 3 of section 13).

**One added pair.** P2-14 (M2) replaces the last paragraph of the new file's module docstring, which at M1 says that `MENTION_FANOUT_RUNXFAIL=1` runs the built cases as plain cases and which P2-12 makes false: the switch is gone and `built` is a no-op. The Builder noticed it when it read the finished file. P2-14 changes the new file's M2 blob and no other.

**Measured.** M0 (before M1): the 11 existing files of the two G2 commands collect 176 tests (the new file is not in the tree yet). G1 at M1: `1 passed, 4 xfailed`; with `MENTION_FANOUT_RUNXFAIL=1` (the new file alone): `4 failed, 1 passed`, every failure at an `assert` in the case's own body (B1 and B2 find no owner where the three expected owners should be, B3 an empty list of recalled reflections, B4 the owner absent from an empty map); no failure line names another exception. G2 at M2: command 1 (4 files) `37 passed` (the new file's 5 and the three existing files' 32), command 2 (8 files) `144 passed`; the architecture check passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`); 181 tests collected over the 12 files (176 + 5), every file of the old list with the same count. G3: `AD/BF ledger is current`, `tests/test_ad1184_ad_ledger.py` 33 passed, and no AD or BF number moves (the regeneration changes the snapshot's `captured_at`, `head` and `subject_count`, the report's git-log row and two skipped-line numbers of `PROGRESS.md`).

**Blobs** (the LF blobs the real build equals). After M1: `tests/test_mention_fanout_episode_owner.py` `306bee6aa686623bc6238e6731a579b131ed6d69`. After M2: `src/probos/routers/chat.py` `1b9e5142e8926f060638b31ce2da6417d5e1379d`, `tests/test_ad719_episodic_writes.py` `7d2b710e8ecba7e9677b1107cee85c083e10389a`, `tests/test_ad791g_main_chat_thread.py` `da6dbece1071d2a96bf2e73ddd7586ec4f81ac92`, `tests/test_bf813_denial_consumers.py` `684a802dcfcf60673808927e7c99283a3e8914bd`, `tests/test_mention_fanout_episode_owner.py` `1fd6ca18d3a591bfb2cf0c7022bd09b4f354dcfb`. After M3, dated 2026-11-14 and before the ledger pair is regenerated: `PROGRESS.md` `7bafb3b08d01de06f7750742f2f4f2ae761a418d`, `DECISIONS.md` `c8d64e03abce1e64f05838f4e4a58c7910eec4c4`.

**Mutation rows.** Each row's line was replaced whole in the built file (M2's head), the four test files of G2's first command run alone, the file restored and its blob checked: 15 runs (rows 14 and 15 rebuild the test file from M1's text with the other pairs of that file applied forward, because P2-8's REPLACE occurs twice in the finished file). 13 match their cells exactly. **Row 6** (`source="direct"`) is also killed by two cases of `test_ad719_episodic_writes.py` (`test_fanout_writes_one_episode_per_reply` and `test_fanout_skips_episode_for_stub_reply`); that file's third case, `test_fanout_episode_source_tag_distinct`, skips instead of failing, because its spy sees no `multi_agent_chat` episode. **Row 11** (`if False:`) is also killed by `test_ad719_episodic_writes.py::test_fanout_skips_episode_for_stub_reply` and, in `test_bf813_denial_consumers.py`, by `test_a_refused_recipient_is_not_recorded_as_having_spoken` and `test_a_failed_delivery_is_also_kept_out_of_episodic_memory`, besides K1. The cells of rows 6 and 11 above now list these. Row 15's one failure is `assert 'chat' == 'dag'` in `test_fanout_episode_anchored_both_branches`. These results are for a tree whose files equal the blobs above.

**Probe and re-read** (synthetic; nothing from a vessel; not committed). The real `DreamAdapter.build_episode` was called as the base route calls it (a result with a `response` and an `agent_ids` key and no plan), with a control that asserts its own premise (a result that carries a plan keeps its agent id): the episode has `agent_ids=[]`, `outcomes=[]`, `reflection=None`, source `direct` and the frame `dag` / `dag_execution`. Re-read (grep) in the oracle tree, whose files other than the five this slice edits are `5275d008`'s: `startup/finalize.py:6214` builds `DreamAdapter(` and `runtime.py:3721` assigns it; the only other `build_episode` callers are `runtime.py:6150` and `experience/renderer.py:486`; `config/system.yaml:141-142` ship `group_episode_enrichment_enabled: true` and `group_reflection_max_chars: 600`.

**Not measured here:** L2's migration conditions, L3 to L7 (what other code does with these episodes), the live vessel, and the D7 count (it needs a copy of a vessel's data, which the Captain authorises).

## 16. Amendment A2 (2026-11-14): review round 1 triaged, no code change

Review round 1 (a Diff Reviewer on `gpt-6.1-sol`, candidate `e5a40255`) found four P2 items, all marked ordinary reach, two of them regressions. The Architect decided that none needs a code change: each comes from a consumer this change does not alter, and a sibling path already shows it. For an owner-scoped reader, the base left no agent an episode of its own (its episodes had no owner: B3); the candidate leaves one to each agent whose episode the storage gate admits, which is every agent unless sibling episodes are near-duplicates (L12). An unscoped reader is a separate case (L12, amended by A3). A2 records them; all four are also recorded on #1523 as one comment, and no issue is filed.

| Finding | What it measured | Decision | Where |
|---|---|---|---|
| F1 | the shared storage gate keeps one of three identical replies (the base stored three ownerless, input-only rows: an unscoped reader such as `_why` found them, an owner-scoped reader did not) | limit; the gate's owner-blindness filed as #1798 (A3) | L12 |
| F2 | a long reply loses its tool-failure disclosure, and the failure fields stay empty | limit | L14 |
| F3 | the Oracle's episode projection carries only `user_input` | not a defect of this change | L5 amended |
| F4 | the dream replay writes a weight under the owner's sovereign id that slot-keyed readers do not see; the base wrote none | limit | L13 |

What A2 changes: the provenance line (header); L5; L12 to L14, added after L11 (section 10); and the two tracker entries, by the pairs P4-1 and P4-2 below, which apply to `DECISIONS.md` and `PROGRESS.md` as they are at `e5a40255`. The route, the tests and the 15 mutation rows of section 9 are unchanged, so the blobs of section 15 hold. The repair commit's gates: the two message scans of section 5, `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` (no AD or BF row moves), then the broad gate on the new head. Round 2 is a delta review of that commit: the `file:line` citations of L5 and L12 to L14 against `e5a40255`; the sibling-path claims (the group fan-out goes through the same gate; the 1:1 reply's sovereign-keyed `direct_message` outcome exists; no reader of `failed_tool_names` exists in `src/`); and no `AD-` or `BF-` token in the tracker lines.

**P4-1.** `DECISIONS.md`: the Residual line of this slice's entry names L12 to L14 and the review commit.
SEARCH:
```
- *Residual.* L1 to L11 of the contract. *Reversal.* Revert the three commits of the slice, M3 then M2 then M1; episodes stored meanwhile stay valid (owned, with the reply).
```
REPLACE:
```
- *Residual.* L1 to L14 of the contract. L12 to L14, from the first review, are the shared storage gate's owner-blind near-duplicate check, the dream replay's edge under the sovereign id and the front-truncated reply without the tool-failure facts; each is also true of a sibling path and is recorded on #1523. *Reversal.* Revert the slice's commits after the contract, newest first (the review commit, M3, M2, M1); episodes stored meanwhile stay valid (owned, with the reply).
```

**P4-2.** `PROGRESS.md`: the Change line of this slice's entry names the limits recorded from the first review.
SEARCH:
```
- **Change.** One `Episode` construction, no branch, as the group-chat fan-out has built its episode since it met the same trap: owner `resolve_sovereign_id_from_slot(<slot>, runtime.identity_registry)` (the slot id where the slot has no certificate), the reply in `outcomes` (500 characters) and in `reflection` as `<callsign> said: <reply>` (600 characters, the group fan-out's shipped cap), source `multi_agent_chat`, frame `chat` / `at_mention_fanout` with participants `captain` and the callsign, then the main-chat thread id as before. A refused or failed reply still stores nothing. Episodes already stored without an owner are not rewritten: they hold no reply. A new test file drives the route with a real adapter, a real episodic store and a registry double that maps slots to sovereign ids, and recalls each episode as its owner by the reply's words; three existing test files that forced or faked the adapter branch say why inline. Contract `prompts/mention-fanout-episode-owner.md`. Refs #1794.
```
REPLACE:
```
- **Change.** One `Episode` construction, no branch, as the group-chat fan-out has built its episode since it met the same trap: owner `resolve_sovereign_id_from_slot(<slot>, runtime.identity_registry)` (the slot id where the slot has no certificate), the reply in `outcomes` (500 characters) and in `reflection` as `<callsign> said: <reply>` (600 characters, the group fan-out's shipped cap), source `multi_agent_chat`, frame `chat` / `at_mention_fanout` with participants `captain` and the callsign, then the main-chat thread id as before. A refused or failed reply still stores nothing. Episodes already stored without an owner are not rewritten: they hold no reply. A new test file drives the route with a real adapter, a real episodic store and a registry double that maps slots to sovereign ids, and recalls each episode as its owner by the reply's words; three existing test files that forced or faked the adapter branch say why inline. Recorded limits from the first review (contract L12 to L14, on #1523): the shared storage gate's near-duplicate check is owner-blind, so agents of one fan-out who reply alike keep one episode between them, as in the group fan-out; the dream replay strengthens the reply's `direct_message` edge under the sovereign id, as it already does for every 1:1 reply; a long reply is stored front-first, so a tool-failure disclosure past the cut is not in the episode. Contract `prompts/mention-fanout-episode-owner.md`. Refs #1794.
```

## 17. Amendment A3 (2026-11-14): review round 2 triaged, no code change

Review round 2 (`gpt-6.1-sol`, a delta of `e5a40255..b694b31f`) found that L12 and section 16 said the base's rows were unrecallable; an unscoped reader (`IntrospectionAgent._why`) found them (P2), and section 16 contradicted L12's survivor count (P3). Both are corrected by P5-2 to P5-4. The loss belongs to the shared gate: it is owner-blind, and the group fan-out on main reaches it independently, with a lower trigger. The Architect filed it as #1798 (the fix: compare only episodes with the same owner) instead of adding a route-level opt-out, which would change a public signature, turn off dedupe for this route only and leave the group fan-out exposed. L12 moves from #1523 to #1798; L13 and L14 stay on #1523. The route, the tests, the mutation rows and the trackers are unchanged. Gates: those A2 names. Round 3 is a delta review of this commit: the `file:line` citations of P5-2, and that the threshold arithmetic matches `storage_gate.py` and `similarity.py:17`.
