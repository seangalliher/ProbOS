# AD-1356 S3 and S4 (#1722): the elevated tier goes to the chain of command, and the Captain sets who decides each tier

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02 (amendment A1: the count-keyed config golden, the replay's `--registered-ids`, the sentences that said every action is the Captain's, P1-2 re-anchored on S2's repaired head, the head-text sweep; amendment A2: P1-3 re-anchored on S2's frozen head `bfb6b72d`, the Status, Base and Re-run text brought up to date, and two sentences that called the confinement's set the tools that run with no approval; amendment A3: the contract's sentences audited before the build: BF-946's shared files, the L1 line number, §14's external claims rewritten against their sources, the absence records A2, A4, A5 and A8 widened to generic consumers, "read by no code", the universals in §15, §16 and the test texts (two test names), the replay's `mcp:` buckets, and P1-32 to P1-34 for three comments and a log message that said an admitted call ran under the Captain's approval (A12)); the orchestrator (Claude Sonnet 5.5), 2026-11-02, before the build: the Status line names BF-946's merge, section 12 records the oracle's re-run on A3, and record sentences are brought in line with the head and the sources (section 10's census sentence, L2's last sentence, section 14's CrewAI per-tool sentence, the AutoGen and CrewAI row texts, and section 16.4's flag-off sentence); no pair, block or SEARCH changed; the orchestrator again, 2026-11-03, after review round 1 (amendment R1: N2-1 exits 2 before anything is written when `--receipt` names the copy or one of its SQLite sidecars or when `--since` or `--until` is not finite, N2-2 gains R4, section 10 gains RY-21 to RY-25, P3-1 loses its clause on the tools a run calls directly and says which two fields `tier_decider` reads, and the other sentences the review found false are deleted: the Gravitee clause and the overdue-project bullet of section 14, the absence parenthetical of section 15 item 3, and "writes only the receipt" of item 10; no SEARCH and no other pair changed); the orchestrator once more, 2026-11-03, after review round 2 (amendment R2: N2-1 also compares a `--receipt` that exists with the copy and its sidecars by file identity, so a second hard-link name for the copy is refused; N2-2's R4 gains a hard link and a respelled sidecar; section 10 gains RY-26; and two sentences the review found false are deleted: the claim in section 14 that neither Gravitee source says who the approver should be, and the sentence in section 10 on what the census prints; no SEARCH and no other pair changed)
**Status:** built on main after BF-946 merged (merge commit `f31afa56`, PR #1739); AD-1356 S1 and S2 merged as main `b773c662`, whose tree is S2's frozen head `bfb6b72d`'s. **Base:** drafted on S2's head `f0c935a1` (main `e9140fcb` + S1 + S2 M1, M2 and the campaign bullet); S2 is frozen at `bfb6b72d` (review round 3 READY). A1 re-anchored P1-2 on S2's repaired head `06dd7539`, and P1-2 applies on the frozen head; A2 re-anchors P1-3 on the frozen head, whose round-2 repair shortened `routine_tool_ids`'s docstring. **Dependencies:** AD-1356 S1 and S2 (#1722), BF-946 (#1723; it merges first, edits `DECISIONS.md` and `PROGRESS.md` above this contract's anchors, and regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`). **Tier:** M1 HIGH (changes who authorises an agent-work call), M2 STANDARD (a read-only script and its test), M3 STANDARD (trackers and ledger). **Estimated tests:** 3 new files (14 test functions, one parametrised ×3), 5 edited test files.
**AD number:** AD-1356, held by the title of #1722; `scripts/ad_ceiling.py` on 2026-11-02: ceiling AD-1356, next AD-1357. S3 and S4 are slices; no new number.

**Which text describes the head.** §1 to §3 describe `f0c935a1`; line numbers are that commit's. The head is what §7 and §8's pairs and new-file blocks produce, applied in order on the merged base. **P1-1, P1-2, P1-3, P1-11, P1-15, P1-16, P1-18 and P1-33 quote text S1 or S2 wrote (P1-2 and P1-3 as of S2's frozen head `bfb6b72d`); N1-1 and N1-2 import S2's test helpers.** Every other SEARCH quotes text from before S1. A SEARCH that no longer matches goes back to the Architect and is not rebased by hand. Where prose differs from a block, the block wins. Head text means every docstring, comment, log message, error string, agent-facing string, config description and test docstring in those blocks, plus §8's tracker entries and §5's commit messages.

## 1. Problem

On `f0c935a1`:

1. `classify_capability_request` returns `CAPTAIN_RESERVED` for every `action` (`delegated_approvals.py:171-172`, "Q1: every action, repair included"). So an agent-work call S2 calls elevated (`find_mcp_tool`, `list_files`, the web reads) can only be decided by the Captain. The Captain lifted Q1 for elevated agent-work calls on 2026-10-31.
2. The S2 table calls every `mcp:` tool critical (`tools/effect_tiers.py:41-49`). S2's table does not read AD-1019b's `McpToolRisk` (`integrations/mcp_bridge/risk.py:34-39`): `_McpTool.effective_risk()` (`agentic_dispatch.py:1741-1760`) applies it when the tool is invoked, and `mcp_workbench`'s `_effective_risk` reads it when it lists and offers tools.
3. A run's directly-run set is fixed to the routine tier (`agent_work_runner.py:611-613`). The Captain has no setting for who decides a tier, and `ToolCallConfinement` refuses an empty set (`agentic_dispatch.py:354`).
4. The agent and the HXI are told the Captain decides every filed call: `CONFINED_CALL_FILED` and `CONFINED_CALL_NOT_FILED` (`agentic_dispatch.py:305-313`), `BLOCKED_REASON` (`agent_work_runner.py:86`), and the filed rationale "outside the read-only set" (`:729`). After S3 that is false for elevated calls.
5. #1722 acceptance 1 needs `scripts/replay_approval_tiers.py`, which does not exist (§12 A6).

## 2. Solution

- **M1:**
  - **Table (`tools/effect_tiers.py`).** It gains the decider names (`auto`, `chief`, `captain`) and four functions:
    - `tier_decider`: the Captain's setting for routine and elevated; critical is always `captain`.
    - `direct_tool_ids`: a run's directly-run set, the listed tools whose tier's decider is `auto`.
    - `filed_call_tier`: a call's tier when it is decided. A path read is classified as if reads were unconfined. An `mcp:` tool takes its risk from its live registration.
    - `mcp_tool_tier`: OPEN → elevated, anything else → critical.
  - **Classifier.** `classify_capability_request` classifies an `agent_work_call` request through those functions. An `auto` or `chief` decider → `NON_DESTRUCTIVE`; `captain` or critical → `CAPTAIN_RESERVED`. Every other action stays `CAPTAIN_RESERVED`. AD-1213 routing is unchanged.
  - **Config.** `ApprovalInboxConfig` gains three fields. The service reads the routine and elevated fields inside its decision lock, and the runner reads them at each run's start; no decision reads the critical field.
  - **Confinement.** `ToolCallConfinement` accepts an empty set.
  - **Agent-facing text.** The four texts in §1.4 stop naming the Captain.
  - **Generated files.** The config facade baseline and `config-reference.md` are regenerated.
- **M2:** `scripts/replay_approval_tiers.py`, which replays a copy of `capability_requests.db` read-only and writes a JSON receipt. Its test runs on a synthetic copy.
- **M3:** trackers and ledger.

## 3. Decisions (ranked by correctness, safety, compatibility, architectural fit, reversibility, validation cost; the first option is chosen)

**D1. How S3 reads a request's tool and tier.**
1. **Chosen: from the persisted payload, classified when the call is decided.**
   - *Payload.* `agent_work_call(req)` (`capability_request.py:155-175`) yields the validated six-key payload, `action == "agent_work_call"`, with the scope bound to its own `work_item_id`. The tool is `payload["tool_id"]`.
   - *Tier.* `filed_call_tier` (`effect_tiers`). A native id is `tool_tier(tool_id, reads_confined=False)`. A filed `read_file` or `codebase_read_source` is therefore always critical, which answers S2 L10: the classifier never reads the roots, so changing them after a call was filed cannot widen who decides it.
   - *MCP.* An `mcp:` id is read from `tool_registry.get(id)`, the registry the service already holds (`finalize.py:3383`). The registration must be enabled and carry the same `tool_id`; the risk is `tool.effective_risk()`, mapped with `risk is McpToolRisk.OPEN` (an identity check, so a str or StrEnum cannot spoof it). `McpToolRisk` is imported lazily inside `mcp_tool_tier`, because importing `integrations.mcp_bridge` loads the whole bridge (`mcp_bridge/__init__.py:8-12`). No ranked layer is crossed: `tools`, `integrations` and the root module are unranked (`check_architecture_principles.py:80-85`).
   - *Malformed or other actions.* A malformed agent-work payload is not an `agent_work_call`, so it falls into the "other action" branch: `CAPTAIN_RESERVED`, as are repair, browser and `approve_candidate` (DECISIONS.md:10992). An unknown tool is critical.
2. Record the tier at filing in the payload. Rejected: DD-1's exact six keys are a persisted contract that the HXI mirrors (`capability_request.py:160-163`, `ui/e2e/fixtures/ad1347-action-payload-rows.json`).
3. Read the live `read_roots` at decision time. Rejected: it adds a runtime dependency to a pure classifier, and lets a change to the roots after filing widen who decides a filed read.
4. Parse the rationale. Rejected: free text is never an authority input.

**D2. The minimal S4.**
1. **Chosen: three `ApprovalInboxConfig` fields** (`config_models/experience.py`, appended after AD-1214's fields):
   - `agent_work_routine_decider: Literal["auto","chief","captain"] = "auto"`
   - `agent_work_elevated_decider` (same type) `= "chief"`
   - `agent_work_critical_decider: Literal["captain"] = "captain"`, which no decision reads.
   - *Meanings.* `auto`: the run calls the tier's tools directly (`direct_tool_ids`, read at run start), and the classifier decides a filed call of the tier as under `chief`. `chief`: AD-1213's route decides a filed call. `captain`: a filed call is `CAPTAIN_RESERVED`.
   - *Critical is enforced twice.* By Pydantic at parse time (`POST /api/config` constructs a fresh `SystemConfig`, `routers/config.py:248-260`, so it answers 422 and persists nothing), and by `tier_decider`, which never reads a critical setting.
   - *Empty set.* `ToolCallConfinement` accepts an empty set (the runner builds one exactly when neither routine nor elevated is `auto`).
   - *Defaults* are the issue's table (routine `auto`, elevated `chief`): with zero config a run's direct set is S2's routine set, and a filed elevated call goes to AD-1213's route.
   - *Rejected alternatives:*
     - Fields in `AgentWorkConfig`: it needs a second settings provider in `DelegatedApprovalService` plus finalize wiring, whereas the service already re-reads `approval_inbox` inside the lock (`delegated_approvals.py:866`).
     - No critical field: `SystemConfig` ignores unknown keys (no `extra="forbid"`, `config.py:3906`), so a typed `critical: chief` would be silently ignored.
     - A dict with a validator: weaker typing.
     - Keep the non-empty invariant and limit routine to `auto`: contradicts "routine and elevated are configurable".
     - An `auto` check at gate time (it would also cover OPEN MCP under `auto`): puts registry reads in the runner's gate. Considered, deferred (L3).
2. A section-registry descriptor so the HXI shows the fields. Deferred: `POST /api/config` already takes any path, and the Captain sets the values himself.

**D3. `delegated_approvals_enabled` off.** Unchanged and verified:
- `_wire_delegated_approvals` returns before building anything (`finalize.py:3331-3332`), so no review tool is registered.
- `DelegatedApprovalService.decide` refuses `NOT_ENABLED` (`delegated_approvals.py:607-608`), and `_verdict` re-reads the flag inside the lock (`:867-868`).
- Test CC6 covers the whole path, from the work item to the Captain's approval resuming it.

**D4. The replay script.**
1. **Chosen: M2 of this contract, after the classification it replays.** It opens a copy read-only with `?mode=ro` and hashes the database file before and after. It needs no registry and no ontology: which tool ids exist on the vessel is the operator's input, `--registered-ids` (A1). The test (R1 to R4) files a synthetic 28-row copy through the real `CapabilityRequestStore`.
   - *Why `--registered-ids`.* S2's table lists no critical id (critical is the default), so offline the script cannot tell a registered unlisted tool (`run_python`: critical, the Captain's) from a nonexistent one (refused by S1.1 before the gate). `--registered-ids` is read only for a non-`mcp:` id the table does not list: in it, `critical_captain`; not in it, `unregistered`; with no argument, `unlisted`. An `mcp:` id is `critical_captain` offline. Rejected: building a `ToolRegistry` in the script (it needs the runtime, and `run_python` is registered lazily at `agentic_dispatch.py:3152-3158`, so no static list of registered ids exists); a hard-coded id list (it goes stale silently).
   - *Rollout:* the orchestrator copies `capability_requests.db`, plus its `-wal` and `-shm` files if present, out of `%LOCALAPPDATA%\ProbOS\data` while the vessel is stopped. It runs `python -P scripts/replay_approval_tiers.py --db <copy> --since <epoch 2026-10-31T22:10:00Z> --until <epoch 2026-11-01T04:30:00Z>`, establishes from the code which of the receipt's `unlisted_tool_ids` the vessel registers, reruns with `--registered-ids <those ids>`, and checks `requests == 28`, `captain_routed == 3` and `counts["unregistered"] == 3`.
   - *What the receipt can show offline:* the `unregistered` ids (as judged by the operator's `--registered-ids`) and the 9 `elevated_chief` requests (to be checked against who filed them; L7).
2. A separate slice after S3/S4. Rejected: the acceptance is S3's.
3. Reading the live file in a test. Rejected: the live database is the Captain's.

**D5. Audit and expiry.** Nothing is added; verified:
- Every delegated decision appends a `delegated_approval` entry before the commit, and is refused without one (`delegated_approvals.py:615-616`, `:670-675`). The entry carries decider, role, class, target, status and reason, plus the delegation id on a First Officer route (`:467-499`).
- Captain decisions are audited while the feature is on (`:780-810`).
- Each delegated decision notifies the Captain. Pre-clearance does not apply to `action` requests (`decision_pre_clearance.py:188-194`; schema `kind IN ('grant','install','skill')`, `:82`).
- First Officer delegations always expire (`expires_at` NOT NULL, DECISIONS.md:11466).
- No standing rule exists for agent work. The delegated route takes no rule input (`decide(agent_id, *, queue, request_id, approve, reason)`, `:573-575`), and the Captain's route refuses one (`routers/capability_requests.py:624`).
- The audit entry keeps its 17 keys; the target names the tool (`list_files.agent_work_call @ agent_work:<id>`).

**D6. Agent-facing texts.**
- `CONFINED_CALL_FILED`/`NOT_FILED` become "needs approval" and "the tools that run directly". No test on `f0c935a1` pins their text by value (A7); N1-1 pins the new filed text's first sentence and `BLOCKED_REASON` by value, on purpose. `classify_tool_fault_error` and `_NEVER_RAN_REFUSALS` hold them by name (`agentic_dispatch.py:331-334`, `:2153`).
- `BLOCKED_REASON` and the rationale are reworded. New items only (L8).
- S2's "Routine reads run directly." is kept (pinned by S2 ET3/RX-10): L5.

**D7. How a chief learns a request awaits them.** No push is added. Under AD-1213, deciders pull through `review_requests` during their own turn (DECISIONS.md:11468); a push is new state (S5-adjacent). The rollout live check counts chief decisions on elevated requests (L1). If chiefs who hold the tool decide none of them on the first evening, the orchestrator files a follow-up for a nudge seam.

**Config:** three fields (D2). No method is added to `DelegatedApprovalService`, `AgentWorkRunner` or `ToolCallConfinement`; the lines changed inside `DelegatedApprovalService` are net zero (§13).

## 4. Milestones and gates

| M | Tier | Pairs | Gate |
|---|---|---|---|
| M1 | HIGH | P1-1 to P1-34, N1-1, N1-2, the two regenerated files | G1 |
| M2 | STANDARD | N2-1, N2-2 | G2 |
| M3 | STANDARD | P3-1, P3-2, the ledger | G3 |

**G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s3_chain_of_command.py tests/test_ad1356_s4_who_decides.py tests/test_ad1356_s2_tool_effect_table.py tests/test_ad1213_delegated_approvals.py tests/test_ad1214_decision_pre_clearance.py tests/test_ad1214_decision_pre_clearance_store.py tests/test_ad1347_s3_execution.py tests/test_bf947_multi_call_agent_work.py tests/test_bf947_confinement_answer.py tests/test_ad1356_s1_unknown_tools.py tests/test_ad1356_s1_recovery_reads.py tests/test_ad1156_plan_execute_mode.py tests/test_ad1270e2c_experience_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_config_reference_current.py tests/test_ad741_config_api.py -q -n 0`, then:
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py --check`

**G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_replay_approval_tiers.py -q -n 0`

**G3:**
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`

## 5. Commit messages

- M1: `AD-1356 S3 and S4 M1: the chain of command decides elevated agent-work calls; the Captain sets who decides each tier`
- M2: `AD-1356 S3 and S4 M2: the read-only approval-tier replay`
- M3: `AD-1356 S3 and S4 M3: trackers and ledger`

## 6. Tests

| Id | File | Test | Covers |
|---|---|---|---|
| CC1 | s3_chain_of_command | `test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it` | Acc. 6, 7, 8; D6 texts |
| CC2 | s3_chain_of_command | `test_a_chiefs_own_elevated_call_and_another_departments_chief_leave_it_with_the_captain` | Acc. 6 |
| CC3 | s3_chain_of_command | `test_a_critical_call_stays_with_the_captain_under_the_most_permissive_settings` | Acc. 2 |
| CC4 | s3_chain_of_command | `test_a_filed_path_read_stays_with_the_captain_after_read_roots_are_set` | S2 L10 |
| CC5 | s3_chain_of_command | `test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk[open,confirm,reaped]` | AD-1019b mapping |
| CC6 | s3_chain_of_command | `test_with_delegated_approvals_off_a_filed_elevated_call_waits_for_the_captain` | D3 |
| WD1 | s4_who_decides | `test_with_elevated_set_to_auto_list_files_runs_with_nothing_filed` | S4 auto |
| WD2 | s4_who_decides | `test_with_routine_and_elevated_set_to_captain_a_routine_call_is_filed_and_only_the_captain_decides` | S4 captain; empty set |
| WD3 | s4_who_decides | `test_with_routine_set_to_chief_a_routine_call_is_filed_and_the_chief_decides_it` | S4 chief |
| WD4 | s4_who_decides | `test_critical_is_the_captains_under_every_setting_and_no_config_value_moves_it` | Acc. 2 boundary; POST /api/config |
| R1 | replay_approval_tiers | `test_the_31st_replays_to_three_captain_decisions_and_the_copy_is_unchanged` | Acc. 1 |
| R2 | replay_approval_tiers | `test_with_reads_unconfined_the_two_path_reads_go_to_the_captain_and_a_missing_copy_is_refused` | Acc. 1 |
| R3 | replay_approval_tiers | `test_without_registered_ids_run_python_and_the_nonexistent_tools_stay_unlisted` | D4, no `--registered-ids` |
| R4 | replay_approval_tiers | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` | Acc. 1; the replay's argument boundaries |

**Edited test files:**
- `tests/test_ad1347_s3_execution.py` (the empty-set pin, P1-21).
- `tests/test_ad1270e2c_experience_models.py` (`EXPECTED_DUMPS`, P1-22).
- `tests/test_ad1152_agentic_correlation.py` (the AD-1152 golden, P1-23).
- `tests/test_ad1270e1_config_facade.py` (the field-count golden, P1-24).
- `tests/test_ad1213_delegated_approvals.py` (its module docstring, P1-28).

## 7. The contract

### 7.1 M1

**P1-1** `src/probos/tools/effect_tiers.py` (**quotes S2's N1-1**)

SEARCH:
```
from __future__ import annotations

from typing import Final

TIER_ROUTINE: Final = "routine"
```
REPLACE:
```
from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger(__name__)

TIER_ROUTINE: Final = "routine"
```

**P1-2** `src/probos/tools/effect_tiers.py` (**quotes S2's N1-1**)

SEARCH:
```
A tool's tier names who authorises an agent-work call to it, in AD-676's names: a ``routine`` call runs with no
approval. A tool is in the table only by name. A tool id
the table does not list (a new or renamed tool, every ``mcp:`` tool) and an id that is not a str are critical.

``routine_tool_ids`` is what a run reads (``agent_work_runner``); ``tool_tier`` classifies one id. The members are
seeded from the plan-mode read set (``cognitive.agent_mode.PLAN_MODE_TOOL_IDS``, held to reads by
``tests/test_ad1156_plan_execute_mode.py``) and from ``execution.effect_broker``'s effect classes, never from the rank
grant matrix (``derive_tool_permission``), which records what a rank is granted, not what a tool does. Pinned member by
member in ``tests/test_ad1356_s2_tool_effect_table.py``. Stdlib only.
"""
```
REPLACE:
```
A tool's tier, in AD-676's names, sets who decides an agent-work call to it (``tier_decider``, AD-1356 S4): the
Captain's ``approval_inbox`` setting for a ``routine`` or ``elevated`` tool, and the Captain for a ``critical`` one. A
tool is in the table only by name. A tool id the table does not list (a new or renamed tool) and an id that is not a
str are critical. So is an ``mcp:`` tool, except that ``filed_call_tier`` (AD-1356 S3) takes a filed call's tier from
AD-1019b's risk in the tool's registration (``mcp_tool_tier``).

``direct_tool_ids`` is what a run reads (``agent_work_runner``); ``tool_tier`` classifies one id;
``delegated_approvals.classify_capability_request`` reads ``filed_call_tier`` and ``tier_decider``. The members are
seeded from the plan-mode read set (``cognitive.agent_mode.PLAN_MODE_TOOL_IDS``, held to reads by
``tests/test_ad1156_plan_execute_mode.py``) and from ``execution.effect_broker``'s effect classes, never from the rank
grant matrix (``derive_tool_permission``), which records what a rank is granted, not what a tool does. Pinned member by
member in ``tests/test_ad1356_s2_tool_effect_table.py``. Imports only the stdlib; ``mcp_tool_tier`` imports
``McpToolRisk`` when it is called.
"""
```

**P1-3** `src/probos/tools/effect_tiers.py` (**quotes S2's N1-1**)

SEARCH:
```
def routine_tool_ids(*, reads_confined: bool) -> frozenset[str]:
    """The members ``tool_tier`` holds routine."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS if tool_tier(tool_id, reads_confined=reads_confined) == TIER_ROUTINE
    )
```
REPLACE:
```
def routine_tool_ids(*, reads_confined: bool) -> frozenset[str]:
    """The members ``tool_tier`` holds routine (``direct_tool_ids`` under the default settings)."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS if tool_tier(tool_id, reads_confined=reads_confined) == TIER_ROUTINE
    )


#: AD-1356 S4 (#1722): who decides an agent-work call of a tier (``approval_inbox.agent_work_<tier>_decider``).
#: ``auto``: the run calls the tier's listed tools directly (``direct_tool_ids``), and a filed call of the tier is
#: decided as under ``chief``. ``chief``: AD-1213's route decides a filed call (a department chief at the first hop in
#: the requester's department, the First Officer under a live delegation after the grace period, otherwise the
#: Captain; with ``delegated_approvals_enabled`` off, the Captain). ``captain``: the Captain alone. ``tier_decider``
#: takes no critical setting (``agent_work_critical_decider`` admits only ``captain``).
DECIDER_AUTO: Final = "auto"
DECIDER_CHIEF: Final = "chief"
DECIDER_CAPTAIN: Final = "captain"
_DELEGABLE: Final[frozenset[str]] = frozenset({DECIDER_AUTO, DECIDER_CHIEF})


def tier_decider(tier: object, *, routine: object, elevated: object) -> str:
    """Who decides a call of ``tier``: for ``routine`` and ``elevated``, the Captain's setting for it; for ``critical``
    and anything else, the Captain. A setting that is not exactly the str ``auto`` or ``chief`` is the Captain."""
    if type(tier) is not str or tier not in (TIER_ROUTINE, TIER_ELEVATED):
        return DECIDER_CAPTAIN
    chosen = routine if tier == TIER_ROUTINE else elevated
    return chosen if type(chosen) is str and chosen in _DELEGABLE else DECIDER_CAPTAIN


def direct_tool_ids(*, reads_confined: bool, routine: object, elevated: object) -> frozenset[str]:
    """An agent-work run's direct set (``ToolCallConfinement.tool_ids``): each tool the table lists whose tier's decider
    is ``auto``. With the default settings (routine ``auto``, elevated ``chief``) it is ``routine_tool_ids``. It may be
    empty."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS
        if tier_decider(tool_tier(tool_id, reads_confined=reads_confined), routine=routine, elevated=elevated)
        == DECIDER_AUTO
    )


def mcp_tool_tier(risk: object) -> str:
    """AD-1356 S3: an ``mcp:`` tool's tier from AD-1019b's effective risk. ``McpToolRisk.OPEN`` is elevated;
    ``CONFIRM``, ``CONSENSUS`` and anything that is not that exact member are critical."""
    from probos.integrations.mcp_bridge.risk import McpToolRisk  # loaded only when an mcp: call is classified

    return TIER_ELEVATED if risk is McpToolRisk.OPEN else TIER_CRITICAL


def filed_call_tier(tool_id: object, *, tool_registry: Any) -> str:
    """AD-1356 S3: the tier of an agent-work call that was filed, read when the call is decided.

    A tool that reads a path through the read policy (``READ_POLICY_TOOL_IDS``) is taken as if reads were unconfined, so
    it is critical whatever ``security_infra.read_roots`` says now: a change to the roots after the call was filed never
    widens who decides it. An ``mcp:`` tool takes AD-1019b's risk from its live registration in ``tool_registry``
    (``effective_risk()``); one that is not registered, is disabled, is registered under another id, or whose risk
    cannot be read is critical. Any other id gets ``tool_tier``'s answer.
    """
    if type(tool_id) is not str or not tool_id.startswith("mcp:"):
        return tool_tier(tool_id, reads_confined=False)
    registration = tool_registry.get(tool_id) if tool_registry is not None else None
    if registration is None or registration.enabled is not True or registration.tool.tool_id != tool_id:
        return TIER_CRITICAL
    try:
        return mcp_tool_tier(registration.tool.effective_risk())
    except Exception:
        logger.warning(
            "AD-1356: the risk of MCP tool %s could not be read; its filed call is critical and stays with the Captain",
            tool_id[:80], exc_info=True,
        )
        return TIER_CRITICAL
```

**P1-4** `src/probos/delegated_approvals.py`

SEARCH:
```
A floor stays with the Captain alone: every ``action`` request, every build
whose design context carries ``requires_consensus``, a grant of the review tool
itself, and anything that cannot be classified. No one decides a requisition
they originated.
```
REPLACE:
```
A floor stays with the Captain alone: every ``action`` request but an
agent-work call whose tier's decider is ``auto`` or ``chief`` (AD-1356 S3:
``capability_request.agent_work_call``, classified by ``tools.effect_tiers``
under the Captain's per-tier settings, where a critical tier's decider is the
Captain), every build whose design context carries ``requires_consensus``, a
grant of the review tool itself, and anything that cannot be classified. No
one decides a requisition they originated.
```

**P1-5** `src/probos/delegated_approvals.py`

SEARCH:
```
from probos.approval_authority import CAPTAIN_UNAVAILABLE, FIRST_OFFICER_DELEGATION, REVIEW_TOOL_ID
from probos.capability_request import build_requires_consensus, validate_action_payload
from probos.cognitive.capability_triage import derive_tool_permission, is_non_destructive
```
REPLACE:
```
from probos.approval_authority import CAPTAIN_UNAVAILABLE, FIRST_OFFICER_DELEGATION, REVIEW_TOOL_ID
from probos.capability_request import agent_work_call, build_requires_consensus, validate_action_payload
from probos.cognitive.capability_triage import derive_tool_permission, is_non_destructive
```

**P1-6** `src/probos/delegated_approvals.py`

SEARCH:
```
    pre_clearance_key,
)

if TYPE_CHECKING:
    from probos.ontology.models import Post
```
REPLACE:
```
    pre_clearance_key,
)
from probos.tools.effect_tiers import DECIDER_CAPTAIN, filed_call_tier, tier_decider

if TYPE_CHECKING:
    from probos.ontology.models import Post
```

**P1-7** `src/probos/delegated_approvals.py`

SEARCH:
```
def classify_capability_request(req: Any, *, tool_registry: ToolLookup | None) -> RequestClass:
    """Classify a capability request. Anything not positively recognised is unclassifiable."""
    kind = getattr(req, "kind", None)
    if kind == "action":  # Q1: every action, repair included
        return RequestClass.CAPTAIN_RESERVED
```
REPLACE:
```
def classify_capability_request(
    req: Any, *, tool_registry: ToolLookup | None, routine_decider: object = None, elevated_decider: object = None,
) -> RequestClass:
    """Classify a capability request. Anything not positively recognised is unclassifiable.

    AD-1356 S3: an agent-work call (``agent_work_call``) is classified by ``filed_call_tier`` and ``tier_decider``
    (``tools.effect_tiers``), never by ``derive_tool_permission``, under the Captain's per-tier settings passed as
    ``routine_decider`` and ``elevated_decider`` (``approval_inbox``). A decider of ``auto`` or ``chief`` is
    non-destructive; ``captain``, a critical tier and a setting not passed are Captain-reserved.
    """
    kind = getattr(req, "kind", None)
    if kind == "action":
        call = agent_work_call(req)
        if call is None:  # Q1: every other action, repair included, stays with the Captain
            return RequestClass.CAPTAIN_RESERVED
        tier = filed_call_tier(call["tool_id"], tool_registry=tool_registry)
        decider = tier_decider(tier, routine=routine_decider, elevated=elevated_decider)
        return RequestClass.CAPTAIN_RESERVED if decider == DECIDER_CAPTAIN else RequestClass.NON_DESTRUCTIVE
```

**P1-8** `src/probos/delegated_approvals.py`

SEARCH:
```
    return RequestClass.UNCLASSIFIABLE


def classify_skill_request(req: Any) -> RequestClass:
```
REPLACE:
```
    return RequestClass.UNCLASSIFIABLE


def _capability_class(req: Any, tool_registry: ToolLookup | None, settings: Any) -> RequestClass:
    """``classify_capability_request`` under the live ``approval_inbox`` settings. AD-1356 S4: the per-tier deciders
    are read only for an agent-work call, so a settings object without them still classifies every other request."""
    if agent_work_call(req) is None:
        return classify_capability_request(req, tool_registry=tool_registry)
    return classify_capability_request(
        req, tool_registry=tool_registry,
        routine_decider=settings.agent_work_routine_decider, elevated_decider=settings.agent_work_elevated_decider,
    )


def classify_skill_request(req: Any) -> RequestClass:
```

**P1-9** `src/probos/delegated_approvals.py` (net zero lines inside the class)

SEARCH:
```
            try:
                request_class = (
                    classify_capability_request(decided, tool_registry=self._tool_registry)
                    if queue == "capability" else classify_skill_request(decided)
                )
```
REPLACE:
```
            try:
                request_class = (
                    _capability_class(decided, self._tool_registry, self._settings())  # type: ignore[misc]
                    if queue == "capability" else classify_skill_request(decided)
                )
```

**P1-10** `src/probos/delegated_approvals.py` (net zero lines inside the class)

SEARCH:
```
        if queue == "capability":
            request_class = classify_capability_request(req, tool_registry=self._tool_registry)
            chief_barred = False
```
REPLACE:
```
        if queue == "capability":
            request_class = _capability_class(req, self._tool_registry, settings)
            chief_barred = False
```

**P1-11** `src/probos/cognitive/agentic_dispatch.py` (**quotes S1 text**)

SEARCH:
```
# AD-1347 S3 (#1627): agent-created work runs confined. AD-1356 S1.1: a call whose tool id the executor's registry does
# not hold is refused before the run's set is consulted. Its other calls to the tools in the run's set run as usual; a
# call to any other tool is put to the run's gate, which admits it, files it for the Captain's approval (an AD-1154
# ``action``), answers it (BF-947) or refuses it. Error-shaped and final, in the AD-1154 voice; never defect evidence.
```
REPLACE:
```
# AD-1347 S3 (#1627): agent-created work runs confined. AD-1356 S1.1: a call whose tool id the executor's registry does
# not hold is refused before the run's set is consulted. Its other calls to the tools in the run's set run as usual; a
# call to any other tool is put to the run's gate, which admits it, files it for approval (an AD-1154 ``action``, whose
# decider follows its tier, AD-1356 S3 and S4), answers it (BF-947) or refuses it. Error-shaped and final, in the
# AD-1154 voice; never defect evidence.
```

**P1-12** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```
CONFINED_CALL_FILED: str = (
    "That call needs the Captain's approval before it runs. It was filed for review and did not run. Do not "
    "repeat it: a repeat is folded into the same request. Finish what the read-only tools allow and report "
    "what remains open."
)
CONFINED_CALL_NOT_FILED: str = (
    "That call needs the Captain's approval before it runs, and it could not be filed for review, so it did "
    "not run. Finish what the read-only tools allow and report what remains open."
)
```
REPLACE:
```
CONFINED_CALL_FILED: str = (
    "That call needs approval before it runs. It was filed for review and did not run. Do not repeat it: a "
    "repeat is folded into the same request. Finish what the tools that run directly allow and report what "
    "remains open."
)
CONFINED_CALL_NOT_FILED: str = (
    "That call needs approval before it runs, and it could not be filed for review, so it did not run. Finish "
    "what the tools that run directly allow and report what remains open."
)
```

**P1-13** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```
    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval), ``CONFINEMENT_ANSWERED`` (BF-947: refused with ``CONFINED_CALL_ANSWERED``) or anything else
```
REPLACE:
```
    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for
    approval), ``CONFINEMENT_ANSWERED`` (BF-947: refused with ``CONFINED_CALL_ANSWERED``) or anything else
```

**P1-14** `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```
    def __post_init__(self) -> None:
        if (
            type(self.tool_ids) is not frozenset or not self.tool_ids
            or any(type(tool_id) is not str or not tool_id for tool_id in self.tool_ids)
```
REPLACE:
```
    def __post_init__(self) -> None:
        # AD-1356 S4: ``tool_ids`` may be empty (it is when neither routine nor elevated is ``auto``).
        if (
            type(self.tool_ids) is not frozenset
            or any(type(tool_id) is not str or not tool_id for tool_id in self.tool_ids)
```

**P1-15** `src/probos/agent_work_runner.py` (**quotes S2's P1-1**)

SEARCH:
```
Every run is confined (``ToolCallConfinement``): the executor refuses a call whose tool id its registry does not hold
(AD-1356 S1.1); the routine tools (``tools.effect_tiers.routine_tool_ids``, read once at the run's start, AD-1356 S2)
run as usual; and a call to any other tool is put to the run's gate (``_gate_for``, whose docstring gives its order),
which may file it as an AD-1154 ``action`` request. A run
```
REPLACE:
```
Every run is confined (``ToolCallConfinement``): the executor refuses a call whose tool id its registry does not hold
(AD-1356 S1.1); the tools whose tier the Captain's setting lets run with no approval (``direct_tool_ids`` in
``tools.effect_tiers``, read once at the run's start, AD-1356 S2 and S4) run as usual; and a call to any other tool is
put to the run's gate (``_gate_for``, whose docstring gives its order), which may file it as an AD-1154 ``action``
request, whose decider follows its tier (AD-1356 S3 and S4). A run
```

**P1-16** `src/probos/agent_work_runner.py` (**quotes S2's P1-2**)

SEARCH:
```
from probos.events import EventType
from probos.tools.effect_tiers import routine_tool_ids
from probos.tools.protocol import ToolPermission, ToolResultPresentation
```
REPLACE:
```
from probos.events import EventType
from probos.tools.effect_tiers import direct_tool_ids
from probos.tools.protocol import ToolPermission, ToolResultPresentation
```

**P1-17** `src/probos/agent_work_runner.py`

SEARCH:
```
BLOCKED_REASON: Final = "waiting for the Captain's decision on a tool call outside the read-only set"
```
REPLACE:
```
BLOCKED_REASON: Final = "waiting for a decision on a tool call this work filed for approval"
```

**P1-18** `src/probos/agent_work_runner.py` (**quotes S2's P1-6**)

SEARCH:
```
            agent = self._agents.get(slot)
            filed: list[str] = []
            # AD-1356 S2: the routine tools, read once here; the set does not change during the run. read_file and
            # codebase_read_source are routine only while security_infra.read_roots confines reads.
            confinement = ToolCallConfinement(
                routine_tool_ids(reads_confined=bool(permitted_read_roots(self._runtime))),
                self._gate_for(item.id, _admissions(linked, slot, item.id), filed),
                record=self.carried.recorder(item.id),
            )
```
REPLACE:
```
            agent = self._agents.get(slot)
            filed: list[str] = []
            # AD-1356 S2 and S4: the confinement's direct set, read once here; the set does not change during the run.
            # read_file and codebase_read_source are in it only while security_infra.read_roots confines reads, and a
            # tier's listed tools only while the Captain's approval_inbox setting for that tier is auto. It may be
            # empty.
            inbox = self._runtime.config.approval_inbox
            confinement = ToolCallConfinement(
                direct_tool_ids(
                    reads_confined=bool(permitted_read_roots(self._runtime)),
                    routine=inbox.agent_work_routine_decider, elevated=inbox.agent_work_elevated_decider,
                ),
                self._gate_for(item.id, _admissions(linked, slot, item.id), filed),
                record=self.carried.recorder(item.id),
            )
```

**P1-19** `src/probos/agent_work_runner.py`

SEARCH:
```
            request = await self._requests.file_action_request(
                agent_id, payload, rationale=f"agent work {work_item_id[:8]} called {tool_id}, outside the read-only set",
                work_item_id=work_item_id,
            )
```
REPLACE:
```
            request = await self._requests.file_action_request(
                agent_id, payload, rationale=f"agent work {work_item_id[:8]} called {tool_id}, a call that needs approval",
                work_item_id=work_item_id,
            )
```

**P1-20** `src/probos/config_models/experience.py`

SEARCH:
```
            "AD-1214: ceiling on a decision pre-clearance's lifetime. A longer "
            "request is clamped, not rejected; expires_at is NOT NULL in the "
            "decision_pre_clearances schema."
        ),
    )
```
REPLACE:
```
            "AD-1214: ceiling on a decision pre-clearance's lifetime. A longer "
            "request is clamped, not rejected; expires_at is NOT NULL in the "
            "decision_pre_clearances schema."
        ),
    )
    agent_work_routine_decider: Literal["auto", "chief", "captain"] = Field(
        default="auto",
        description=(
            "AD-1356 S4: who decides an agent-work call to a routine tool "
            "(tools.effect_tiers). auto: the run calls the tier's tools with "
            "no approval. chief: AD-1213's route decides a filed call (a "
            "department chief at the first hop in the requester's department, "
            "the First Officer under a live delegation after "
            "approval_grace_seconds, else the Captain; with "
            "delegated_approvals_enabled off, the Captain). captain: the "
            "Captain alone decides a filed call. Read at each agent-work run's "
            "start and at each decision; a POST /api/config change applies at "
            "restart."
        ),
    )
    agent_work_elevated_decider: Literal["auto", "chief", "captain"] = Field(
        default="chief",
        description=(
            "AD-1356 S4: who decides an agent-work call to an elevated tool "
            "(find_mcp_tool, list_files, web_search, read_page, http_fetch, an "
            "OPEN MCP tool). auto, chief and captain mean what they mean for "
            "agent_work_routine_decider, except that a run never calls an MCP "
            "tool directly, so under auto a filed call to one is decided as "
            "under chief."
        ),
    )
    agent_work_critical_decider: Literal["captain"] = Field(
        default="captain",
        description=(
            "AD-1356 S4: fixed at captain. A filed critical agent-work call "
            "(to a tool the table does not list, run_python, write and shell "
            "tools among them; to an MCP tool not registered and enabled "
            "under its id, or whose AD-1019b risk when the call is decided is "
            "not OPEN or cannot be read; to read_file or codebase_read_source) "
            "is the Captain's alone. Any other value fails validation, and no "
            "decision reads this field."
        ),
    )
```

**P1-21** `tests/test_ad1347_s3_execution.py` (a test that pins the old invariant; updated, not deleted)

SEARCH:
```
    for tool_ids, gate in ((frozenset(), broken), ({"x"}, broken), (frozenset({"x"}), "not callable")):
        with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
            ToolCallConfinement(tool_ids, gate)  # type: ignore[arg-type]
```
REPLACE:
```
    # AD-1356 S4: an empty set is valid (the runner builds one when neither routine nor elevated is auto); a set that is
    # not a frozenset of non-empty str, or a gate that is not callable, is not.
    assert ToolCallConfinement(frozenset(), broken).tool_ids == frozenset()
    for tool_ids, gate in (({"x"}, broken), (frozenset({""}), broken), (frozenset({"x"}), "not callable")):
        with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
            ToolCallConfinement(tool_ids, gate)  # type: ignore[arg-type]
```

**P1-22** `tests/test_ad1270e2c_experience_models.py`

SEARCH:
```
                               'decision_pre_clearance_enabled': False,
                               'decision_pre_clearance_default_ttl_hours': 24,
                               'decision_pre_clearance_max_ttl_hours': 168},
```
REPLACE:
```
                               'decision_pre_clearance_enabled': False,
                               'decision_pre_clearance_default_ttl_hours': 24,
                               'decision_pre_clearance_max_ttl_hours': 168,
                               # AD-1356 S4 appended three fields after the move; the move changed none.
                               'agent_work_routine_decider': 'auto',
                               'agent_work_elevated_decider': 'chief',
                               'agent_work_critical_decider': 'captain'},
```

**P1-23** `tests/test_ad1152_agentic_correlation.py`

SEARCH:
```
    # AD-1214's three inert approval_inbox fields were added after this capture too.
    assert config["approval_inbox"].pop("decision_pre_clearance_enabled") is False
    assert config["approval_inbox"].pop("decision_pre_clearance_default_ttl_hours") == 24
    assert config["approval_inbox"].pop("decision_pre_clearance_max_ttl_hours") == 168
```
REPLACE:
```
    # AD-1214's three inert approval_inbox fields were added after this capture too.
    assert config["approval_inbox"].pop("decision_pre_clearance_enabled") is False
    assert config["approval_inbox"].pop("decision_pre_clearance_default_ttl_hours") == 24
    assert config["approval_inbox"].pop("decision_pre_clearance_max_ttl_hours") == 168
    # AD-1356 S4's three agent-work deciders were added after this capture too; their defaults are the issue's table
    # (routine auto, elevated chief), and this observation runs no agent work.
    assert config["approval_inbox"].pop("agent_work_routine_decider") == "auto"
    assert config["approval_inbox"].pop("agent_work_elevated_decider") == "chief"
    assert config["approval_inbox"].pop("agent_work_critical_decider") == "captain"
```

**P1-24** `tests/test_ad1270e1_config_facade.py` (a golden keyed by count; A10)

SEARCH:
```
    # AD-1346 M3c (#1604) adds AdmissionConfig.shadow_enabled and SystemConfig.admission (1878 -> 1880).
    assert counts["field_definitions"] == 1880  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # AD-1346 M3c (#1604) adds AdmissionConfig.shadow_enabled and SystemConfig.admission (1878 -> 1880).
    # AD-1356 S4 (#1722) adds ApprovalInboxConfig's three agent_work_*_decider fields (1880 -> 1883).
    assert counts["field_definitions"] == 1883  # AD-1206 intentionally adds github_repository.
```

**P1-25** `src/probos/execution/command_approvals.py` (text only; A11)

SEARCH:
```
  past ``expires_at`` (``NOT NULL``); and nothing approved by anyone but the Captain
  under the Captain's authority (every ``action`` request is Captain-reserved,
  ``probos.delegated_approvals.classify_capability_request``). A change of who may
  approve is a change of ``approver_authority``, which strands every older row.
```
REPLACE:
```
  past ``expires_at`` (``NOT NULL``); and nothing approved by anyone but the Captain
  under the Captain's authority (``probos.delegated_approvals.classify_capability_request``
  reserves a ``run_command`` request to the Captain). A change of who may
  approve is a change of ``approver_authority``, which strands every older row.
```

**P1-26** `src/probos/cognitive/repair_approval.py` (text only; A11)

SEARCH:
```
  candidate digest, the authority class and the campaign id. AD-1213 reserves every ``action``
  request to the Captain (``delegated_approvals.classify_capability_request``). Filing runs nothing.
```
REPLACE:
```
  candidate digest, the authority class and the campaign id. AD-1213 reserves a ``repair``
  request to the Captain (``delegated_approvals.classify_capability_request``). Filing runs nothing.
```

**P1-27** `src/probos/config_models/experience.py` (`ApprovalInboxConfig`'s docstring; before the regenerations, which take its schema digest; A11)

SEARCH:
```
    the Captain is marked unavailable). A floor stays with the Captain alone: every
    ``action`` request, every consensus build, and anything that cannot be
    classified. Both records that widen authority -- the First Officer delegation
```
REPLACE:
```
    the Captain is marked unavailable). A floor stays with the Captain alone: every
    ``action`` request but an agent-work call whose tier's decider
    (``agent_work_<tier>_decider`` below, AD-1356 S3 and S4) is ``auto`` or
    ``chief``, every consensus build, and anything that cannot be classified. Both
    records that widen authority -- the First Officer delegation
```

**P1-28** `tests/test_ad1213_delegated_approvals.py` (module docstring; A11)

SEARCH:
```
after a grace period in which the Captain has first refusal. Everything else --
every action, every consensus build, anything that cannot be classified -- stays
with the Captain. Every delegated decision is notified to the Captain and
```
REPLACE:
```
after a grace period in which the Captain has first refusal. Everything else --
every action but an AD-1356 S3 agent-work call whose tier's decider is auto or
chief, every consensus build, anything that cannot be classified -- stays
with the Captain. Every delegated decision is notified to the Captain and
```

**P1-29** `docs/development/self-maintenance-architecture.md` (A11; a symbol reference, so P1-4 and P1-7 do not move it)

SEARCH:
```
| [Chain-of-command approvals](../../src/probos/delegated_approvals.py) and [ApprovalAuthorityStore](../../src/probos/approval_authority.py) | AD-1213: every `action` request stays with the Captain alone (`delegated_approvals.py:12-13`); authority records cannot exist without `expires_at` (`approval_authority.py:62`). |
```
REPLACE:
```
| [Chain-of-command approvals](../../src/probos/delegated_approvals.py) and [ApprovalAuthorityStore](../../src/probos/approval_authority.py) | AD-1213: every repair request stays with the Captain alone (`classify_capability_request` in `delegated_approvals.py`); authority records cannot exist without `expires_at` (`approval_authority.py:62`). |
```

**P1-30** `docs/development/self-maintenance-architecture.md` (A11)

SEARCH:
```
| Authority | The Captain's decision on an action-shaped request in `CapabilityRequestStore`, bound to the candidate digest, with an expiry, re-checked at each boundary. `action` requests stay with the Captain alone (`delegated_approvals.py:171-172`: every action, repair included, is Captain-reserved). The Captain approves each exact candidate digest before its code runs. Agents may prepare candidates as text without approval. Delegated/autonomous grants exist only under D-B2 option (b) or (c); the working default (a) has none. |
```
REPLACE:
```
| Authority | The Captain's decision on an action-shaped request in `CapabilityRequestStore`, bound to the candidate digest, with an expiry, re-checked at each boundary. Repair requests stay with the Captain alone (`classify_capability_request` in `delegated_approvals.py`). The Captain approves each exact candidate digest before its code runs. Agents may prepare candidates as text without approval. Delegated/autonomous grants exist only under D-B2 option (b) or (c); the working default (a) has none. |
```

**P1-31** `docs/development/self-maintenance-architecture.md` (A11)

SEARCH:
```
per-step and delegated work is AD-1213, which keeps every action (repair
included) with the Captain (`delegated_approvals.py:171-172`), and whether a
human approved the exact code before it ran.
```
REPLACE:
```
per-step and delegated work is AD-1213, which keeps every repair request with
the Captain (`classify_capability_request` in `delegated_approvals.py`), and
whether a human approved the exact code before it ran.
```

**P1-32** `src/probos/cognitive/agentic_dispatch.py` (text only; A12)

SEARCH:
```
# AD-1347 S3 A1 (F3): set for the one call a run's confinement admitted under the Captain's single-use approval of that
# exact call, so AD-1154's inbox does not park it again. Credential entry (the inbox's step 3) is still refused.
_CONFINED_ADMISSION: ContextVar[bool] = ContextVar("confined_admission", default=False)
```
REPLACE:
```
# AD-1347 S3 A1 (F3): set for the one call a run's confinement admitted (a single-use approval of that exact call, or
# a workspace-result read, AD-1356 S1.3), so AD-1154's inbox does not park it again. Credential entry stays refused.
_CONFINED_ADMISSION: ContextVar[bool] = ContextVar("confined_admission", default=False)
```

**P1-33** `src/probos/cognitive/agentic_dispatch.py` (text only; **quotes S1 text**; A12)

SEARCH:
```
            # AD-1347 S3 A1 (F3): the gate admitted this call, under the Captain's approval of exactly this call, once,
            # or as a read of a workspace-result path, which needs none (AD-1356 S1.3). AD-1154's inbox below does not
            # park an admitted call (credential entry there stays refused).
```
REPLACE:
```
            # AD-1347 S3 A1 (F3): the gate admitted this call, under an approval of exactly this call, once,
            # or as a read of a workspace-result path, which needs none (AD-1356 S1.3). AD-1154's inbox below does not
            # park an admitted call (credential entry there stays refused).
```

**P1-34** `src/probos/cognitive/agentic_dispatch.py` (text only, a comment and a log message; A12)

SEARCH:
```
            # AD-1347 S3 A1 (F3): the run's confinement admitted this exact call under the Captain's single-use approval
            # of it, so it is not parked again; credential entry (step 3, above) stays refused.
            logger.info("AD-1347: %s.%s for agent %s runs under the Captain's approval of this call", tool_id, action, agent_id[:12])
```
REPLACE:
```
            # AD-1347 S3 A1 (F3): the run's confinement admitted this exact call under a single-use approval of it,
            # so it is not parked again; credential entry (step 3, above) stays refused.
            logger.info("AD-1347: %s.%s for agent %s runs under an approval of this call", tool_id, action, agent_id[:12])
```

**Regenerated in M1:**
- `python -P scripts/check_config_facade.py --update-baseline`, then stage `docs/development/config-facade-baseline.yaml`. The diff is the reviewed artifact: three `ApprovalInboxConfig` field rows, its `schema_sha256`, `SystemConfig`'s `schema_sha256` (it nests `ApprovalInboxConfig`), `surface_counts`, `canonical_dump_sha256`; nothing else.
- `python -P scripts/gen_config_reference.py`, then stage `docs/development/config-reference.md`.

**N1-1** `tests/test_ad1356_s3_chain_of_command.py` (new)

```python
"""AD-1356 S3 (#1722): the chain of command decides a filed elevated agent-work call; a critical one stays with the Captain.

Each test starts from a work item making the call, in the rig of ``tests/test_ad1347_s3_execution.py`` (the real
ontology, crew, stores, executor, AD-855 driver and Captain route), with AD-1213's ``DelegatedApprovalService`` built
from the same stores as ``startup/finalize.py`` builds it, and ends at the item resuming and finishing. On the base this
file fails at import (``probos.tools.effect_tiers.filed_call_tier``).
"""

from __future__ import annotations

import contextlib
import functools
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.api_models import CapabilityRequestDecideRequest
from probos.approval_authority import ApprovalAuthorityStore
from probos.capability_request import requests_for_work_item
from probos.cognitive.agentic_dispatch import _McpTool
from probos.delegated_approvals import AUDIT_CATEGORY, DeciderRole, DelegatedApprovalService, Refusal, RequestClass
from probos.routers.capability_requests import decide_capability_request, fulfil_on_approval
from probos.security.audit import AuditLog
from probos.tools.effect_tiers import TIER_CRITICAL, filed_call_tier
from tests.test_ad1347_s1_agent_work import RANKS, REASON
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _pump, _rig, _seen, _thread_in
from tests.test_ad1356_s2_tool_effect_table import NOTES, _native, _notes, _self_task

FILED = "That call needs approval before it runs."
BLOCKED = "waiting for a decision on a tool call this work filed for approval"
DOCS = "Relay docs: the drift budget is 0.5 mm."


class _Notes:
    """``runtime.notify``'s shape: what the Captain was told."""

    def __init__(self) -> None:
        self.sent: list[SimpleNamespace] = []

    def __call__(
        self, agent_id: str, title: str, detail: str = "", notification_type: str = "info", action_url: str = "",
    ) -> None:
        self.sent.append(SimpleNamespace(agent_id=agent_id, title=title, detail=detail))


class _Bridge:
    """``MCPBridge.invoke``'s shape: records what it is asked and answers with the docs text."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(self, server_url: str, tool_name: str, args: dict[str, Any]) -> str:
        self.asked.append((server_url, tool_name, args))
        return DOCS


@contextlib.asynccontextmanager
async def _chain(
    rig: Any, *, enabled: bool = True, **deciders: str,
) -> AsyncIterator[tuple[DelegatedApprovalService, AuditLog, _Notes]]:
    """``approval_inbox`` with ``enabled`` and ``deciders``, and the service ``finalize._wire_delegated_approvals``
    builds over the rig's stores."""
    inbox = rig.runtime.config.approval_inbox.model_copy(update={"delegated_approvals_enabled": enabled, **deciders})
    rig.runtime.config = rig.runtime.config.model_copy(update={"approval_inbox": inbox})
    authority = ApprovalAuthorityStore(db_path="")
    await authority.start()
    audit, notes = AuditLog(), _Notes()
    service = DelegatedApprovalService(
        capability_requests=rig.requests, skill_requests=None, authority_store=authority,
        agent_registry=rig.runtime.registry, ontology=rig.runtime.ontology, tool_registry=rig.tools,
        work_items=rig.store, audit_log=audit, notify=notes,
        fulfil=functools.partial(fulfil_on_approval, rig.runtime),
        settings=lambda: rig.runtime.config.approval_inbox,
    )
    try:
        yield service, audit, notes
    finally:
        await authority.stop()


async def _decide(service: DelegatedApprovalService, agent_id: str, request_id: str) -> Any:
    return await service.decide(
        agent_id, queue="capability", request_id=request_id, approve=True, reason="Within the department's work.",
    )


async def _captain_approves(rig: Any, request_id: str) -> None:
    decided = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True),
        runtime=SimpleNamespace(capability_request_store=rig.requests),
    )
    assert decided["fulfilled"] is True
    await _pump(rig)


async def _parked_on(rig: Any, item_id: str) -> Any:
    item = await rig.store.get_work_item(item_id)
    assert item is not None and item.status == "blocked"
    [request] = requests_for_work_item(rig.requests, item_id)
    assert request.status == "pending"
    return request


async def _finished(rig: Any, item_id: str) -> None:
    item = await rig.store.get_work_item(item_id)
    assert item is not None and item.status == "done"


def _listing(tmp_path: Path) -> tuple[Path, list[Any]]:
    notes = _notes(tmp_path)
    listing = {"pattern": "*.txt", "path": str(notes.parent)}
    return notes, [_call("list_files", listing, "c1"), _final("Waiting."), _call("list_files", listing, "c2"), _final(ANSWER)]


# CC1
async def test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it(tmp_path: Path) -> None:
    """forge-1's list_files is elevated: filed, the item parks, and the model is told the call needs approval. LaForge,
    forge-1's chief in Engineering, approves it; the decision is audited and the Captain notified once; the item
    resumes and the call runs."""
    notes, script = _listing(tmp_path)
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig) as (service, audit, told):
                item_id = await _self_task(rig, "List the relay notes")
                request = await _parked_on(rig, item_id)
                parked = await rig.store.get_work_item(item_id)
                assert parked is not None and parked.metadata["blocked_reason"] == BLOCKED
                assert request.rationale == f"agent work {item_id[:8]} called list_files, a call that needs approval"
                assert _seen(rig, FILED) and not _seen(rig, "notes.txt")
                outcome = await _decide(service, "laforge-1", request.id)
                assert (outcome.refusal, outcome.role, outcome.request_class, outcome.fulfilled) == (
                    None, DeciderRole.DEPARTMENT_CHIEF, RequestClass.NON_DESTRUCTIVE, True,
                )
                [entry] = [json.loads(e.detail) for e in audit.entries if e.category == AUDIT_CATEGORY]
                assert (entry["decider_id"], entry["decider_role"], entry["request_class"], entry["approve"]) == (
                    "laforge-1", "department_chief", "non_destructive", True,
                )
                assert entry["target"].startswith("list_files.agent_work_call")
                [note] = told.sent
                assert note.detail.startswith("Department chief laforge-1 approved forge-1's action request")
                await _pump(rig)
                await _finished(rig, item_id)
                assert _seen(rig, "notes.txt")
        finally:
            await store.stop()


# CC2
async def test_a_chiefs_own_elevated_call_and_another_departments_chief_leave_it_with_the_captain(
    tmp_path: Path,
) -> None:
    """LaForge's own list_files is his requisition, and Bones (Medical) has no authority over Engineering: both are
    refused, LaForge's list does not offer it, and it waits for the Captain, whose approval resumes the item."""
    notes, script = _listing(tmp_path)
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig) as (service, _audit, _told):
                origin = await _thread_in(rig, "engineering", "forge-1")
                created = await rig.service.create_self_task(
                    "laforge-1", title="List the relay notes", description="", reason=REASON,
                    origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
                )
                assert isinstance(created, AgentWorkCreated), created
                await _pump(rig)
                item_id = created.work_item.id
                request = await _parked_on(rig, item_id)
                assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.OWN_REQUISITION
                assert (await _decide(service, "bones-1", request.id)).refusal is Refusal.OUTSIDE_AUTHORITY
                assert (await service.list_reviewable("laforge-1"))[0] == []
                assert (await rig.requests.get(request.id)).status == "pending"
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert _seen(rig, "notes.txt")
        finally:
            await store.stop()


# CC3
async def test_a_critical_call_stays_with_the_captain_under_the_most_permissive_settings(tmp_path: Path) -> None:
    """hull_survey is not in the table, so critical: with routine and elevated both auto, LaForge is refused as
    Captain-reserved and his list does not offer it; the Captain's approval runs it once."""
    script = [_call("hull_survey", {}, "c1"), _final("Waiting."), _call("hull_survey", {}, "c2"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        async with _chain(rig, agent_work_routine_decider="auto", agent_work_elevated_decider="auto") as (
            service, _audit, _told,
        ):
            item_id = await _self_task(rig, "Survey the hull")
            request = await _parked_on(rig, item_id)
            outcome = await _decide(service, "laforge-1", request.id)
            assert (outcome.refusal, outcome.request_class) == (Refusal.CAPTAIN_RESERVED, RequestClass.CAPTAIN_RESERVED)
            assert (await service.list_reviewable("laforge-1"))[0] == [] and rig.survey.calls == 0
            await _captain_approves(rig, request.id)
            await _finished(rig, item_id)
            assert rig.survey.calls == 1


# CC4
async def test_a_filed_path_read_stays_with_the_captain_after_read_roots_are_set(tmp_path: Path) -> None:
    """With read_roots unset, forge-1's read_file is filed. Setting the roots afterwards does not let LaForge decide
    it. The Captain approves; the resumed run reads under the roots and finishes."""
    notes = _notes(tmp_path)
    read = {"path": str(notes)}
    script = [_call("read_file", read, "c1"), _final("Waiting."), _call("read_file", read, "c2"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[])
        try:
            async with _chain(rig) as (service, _audit, _told):
                item_id = await _self_task(rig, "Read the relay notes")
                request = await _parked_on(rig, item_id)
                security = rig.runtime.config.security_infra.model_copy(update={"read_roots": [str(notes.parent)]})
                rig.runtime.config = rig.runtime.config.model_copy(update={"security_infra": security})
                assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.CAPTAIN_RESERVED
                assert not _seen(rig, NOTES)
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert _seen(rig, NOTES)
        finally:
            await store.stop()


# CC5
@pytest.mark.parametrize("case", ["open", "confirm", "reaped"])
async def test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk(tmp_path: Path, case: str) -> None:
    """An OPEN MCP tool is elevated: LaForge approves forge-1's call and it runs. A CONFIRM tool is critical, and so is
    an OPEN tool no longer registered when its call is decided: LaForge is refused, and after the Captain's approval
    the item finishes with the bridge never asked."""
    bridge = _Bridge()
    tool = _McpTool(
        bridge=bridge, server_url="docs", server_name="docs", server_id="srv-docs", tool_name="search", name="search",
        description="Search the relay docs.", input_schema={"type": "object"},
        server_default_risk="confirm" if case == "confirm" else "open", risk_store=None,
        consensus_invoke=AsyncMock(), authorize=lambda agent_id: True,
    )
    query = {"query": "drift budget"}
    script = [_call(tool.tool_id, query, "c1"), _final("Waiting."), _call(tool.tool_id, query, "c2"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        rig.tools.register(
            tool, provider="AD-1019c", tags=[tool.tool_id, "mcp"], default_permissions=dict.fromkeys(RANKS, "read"),
        )
        async with _chain(rig) as (service, _audit, _told):
            item_id = await _self_task(rig, "Look up the drift budget")
            request = await _parked_on(rig, item_id)
            if case == "reaped":
                assert rig.tools.unregister(tool.tool_id)
            outcome = await _decide(service, "laforge-1", request.id)
            if case == "open":
                assert (outcome.refusal, outcome.role, outcome.fulfilled) == (None, DeciderRole.DEPARTMENT_CHIEF, True)
                await _pump(rig)
                await _finished(rig, item_id)
                assert bridge.asked == [("docs", "search", query)] and _seen(rig, DOCS)
            else:
                assert outcome.refusal is Refusal.CAPTAIN_RESERVED
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert bridge.asked == []
    assert filed_call_tier(tool.tool_id, tool_registry=None) == TIER_CRITICAL


# CC6
async def test_with_delegated_approvals_off_a_filed_elevated_call_waits_for_the_captain(tmp_path: Path) -> None:
    """Off: LaForge's decision is refused as switched off, nothing is audited or notified, and the elevated call stays
    pending with the item parked; the Captain's approval resumes the item and the call runs."""
    notes, script = _listing(tmp_path)
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, enabled=False) as (service, audit, told):
                item_id = await _self_task(rig, "List the relay notes")
                request = await _parked_on(rig, item_id)
                assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.NOT_ENABLED
                assert [e for e in audit.entries if e.category == AUDIT_CATEGORY] == [] and told.sent == []
                await _parked_on(rig, item_id)
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert _seen(rig, "notes.txt")
        finally:
            await store.stop()
```

**N1-2** `tests/test_ad1356_s4_who_decides.py` (new)

```python
"""AD-1356 S4 (#1722): the Captain's per-tier "who decides" setting, with critical fixed at the Captain.

The whole-path tests reuse ``tests/test_ad1356_s3_chain_of_command.py``'s chain on the AD-1347 rig; the boundary test
posts to the real ``/api/config`` route. On the base this file fails at import
(``probos.tools.effect_tiers.direct_tool_ids``).
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from probos.agent_work_runner import APPROVAL_USE_PREFIX
from probos.capability_request import requests_for_work_item
from probos.config_models.experience import ApprovalInboxConfig
from probos.delegated_approvals import DeciderRole, Refusal
from probos.tools.effect_tiers import (
    DECIDER_CAPTAIN,
    ELEVATED_TOOL_IDS,
    ROUTINE_TOOL_IDS,
    TIER_CRITICAL,
    direct_tool_ids,
    routine_tool_ids,
    tier_decider,
    tool_tier,
)
from tests.test_ad1347_s3_execution import ANSWER, WINDOW, _call, _final, _pump, _rig, _seen
from tests.test_ad1356_s2_tool_effect_table import _native, _notes, _self_task
from tests.test_ad1356_s3_chain_of_command import _captain_approves, _chain, _decide, _finished, _parked_on
from tests.test_ad741_config_api import _build_runtime, _client

SETTINGS = ("auto", "chief", "captain")
STOP_ORDERS = [_call("event_log_query", WINDOW, "c1"), _final("Waiting."), _call("event_log_query", WINDOW, "c2"), _final(ANSWER)]


# WD1
async def test_with_elevated_set_to_auto_list_files_runs_with_nothing_filed(tmp_path: Path) -> None:
    """Elevated auto: list_files is in the run's direct set, so it runs, nothing is filed and the item is done."""
    notes = _notes(tmp_path)
    script = [_call("list_files", {"pattern": "*.txt", "path": str(notes.parent)}, "c1"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == [] and _seen(rig, "notes.txt")
        finally:
            await store.stop()


# WD2
async def test_with_routine_and_elevated_set_to_captain_a_routine_call_is_filed_and_only_the_captain_decides(
    tmp_path: Path,
) -> None:
    """The confinement's set is empty, so forge-1's routine event_log_query is filed; LaForge is refused as
    Captain-reserved, and the Captain's approval resumes the item, whose run uses that approval."""
    async with _rig(tmp_path, STOP_ORDERS) as rig:
        async with _chain(rig, agent_work_routine_decider="captain", agent_work_elevated_decider="captain") as (
            service, _audit, _told,
        ):
            item_id = await _self_task(rig, "Read the stop orders")
            request = await _parked_on(rig, item_id)
            assert request.payload["tool_id"] == "event_log_query"
            assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.CAPTAIN_RESERVED
            await _captain_approves(rig, request.id)
            await _finished(rig, item_id)
            assert not await rig.store.claim_work_notice(item_id, "forge-1", APPROVAL_USE_PREFIX + request.id, 0.0)


# WD3
async def test_with_routine_set_to_chief_a_routine_call_is_filed_and_the_chief_decides_it(tmp_path: Path) -> None:
    """Routine chief: forge-1's event_log_query is filed, LaForge approves it, and the resumed run uses the approval."""
    async with _rig(tmp_path, STOP_ORDERS) as rig:
        async with _chain(rig, agent_work_routine_decider="chief") as (service, _audit, _told):
            item_id = await _self_task(rig, "Read the stop orders")
            request = await _parked_on(rig, item_id)
            outcome = await _decide(service, "laforge-1", request.id)
            assert (outcome.refusal, outcome.role, outcome.fulfilled) == (None, DeciderRole.DEPARTMENT_CHIEF, True)
            await _pump(rig)
            await _finished(rig, item_id)
            assert not await rig.store.claim_work_notice(item_id, "forge-1", APPROVAL_USE_PREFIX + request.id, 0.0)


# WD4
def test_critical_is_the_captains_under_every_setting_and_no_config_value_moves_it(tmp_path: Path) -> None:
    """Boundary: agent_work_critical_decider accepts only captain, in the model and through POST /api/config, which
    persists a valid setting for the next start and nothing for a refused one. Under every setting and read policy a
    critical tier is the Captain's and no critical tool is in a run's direct set."""
    defaults = ApprovalInboxConfig()
    assert (defaults.agent_work_routine_decider, defaults.agent_work_elevated_decider) == ("auto", "chief")
    assert defaults.agent_work_critical_decider == "captain"
    for value in ("chief", "auto", "Captain", "", None, 1):
        with pytest.raises(ValidationError):
            ApprovalInboxConfig(agent_work_critical_decider=value)
    for field in ("agent_work_routine_decider", "agent_work_elevated_decider"):
        with pytest.raises(ValidationError):
            ApprovalInboxConfig(**{field: "self"})
    for routine, elevated, confined in itertools.product(SETTINGS, SETTINGS, (True, False)):
        assert tier_decider(TIER_CRITICAL, routine=routine, elevated=elevated) == DECIDER_CAPTAIN
        direct = direct_tool_ids(reads_confined=confined, routine=routine, elevated=elevated)
        assert direct <= ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS
        assert all(tool_tier(tool_id, reads_confined=confined) != TIER_CRITICAL for tool_id in direct)
    for confined in (True, False):
        assert direct_tool_ids(reads_confined=confined, routine="auto", elevated="chief") == routine_tool_ids(
            reads_confined=confined,
        )
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)
    path = Path(runtime.config_path)

    def post(patch: dict[str, str]) -> object:
        csrf = client.get("/api/config").json()["csrf_token"]
        return client.post("/api/config", json={"patch": {"approval_inbox": patch}}, headers={"X-Probos-CSRF": csrf})

    ok = post({"agent_work_elevated_decider": "captain"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["restart_required"] is True
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["approval_inbox"]["agent_work_elevated_decider"] == "captain"
    written = path.read_bytes()
    for patch in ({"agent_work_critical_decider": "chief"}, {"agent_work_routine_decider": "self"}):
        refused = post(patch)
        assert refused.status_code == 422 and refused.json()["error"] == "validation_failed"
        assert path.read_bytes() == written
```

### 7.2 M2

**N2-1** `scripts/replay_approval_tiers.py` (new)

```python
"""AD-1356 (#1722), acceptance 1: replay filed agent-work approvals against the tool-effect table, read-only.

Reads a copy of ``capability_requests.db`` (never the live file, which the Captain's vessel owns), opened read-only, and
says for each ``action`` request filed in the window what AD-1356 S1 to S4 now decide for it. Writes a JSON receipt.

    python -P scripts/replay_approval_tiers.py --db COPY --since EPOCH --until EPOCH [--reads-unconfined]
        [--routine auto|chief|captain] [--elevated auto|chief|captain] [--registered-ids ID,ID] [--receipt PATH]

Buckets: ``<tier>_<decider>`` for an agent-work call (``*_auto``: the run calls the tool directly; ``*_chief``: AD-1213's
route decides it; ``*_captain``: the Captain does); ``recovery_read`` (S1.3's gate admits it); ``unregistered`` (a
non-``mcp:`` id the table does not list and ``--registered-ids`` does not hold: S1.1 refuses it and nothing is filed);
``unlisted`` (such an id, with no ``--registered-ids``: refused or critical, which the script cannot tell);
``input_error`` (a repair whose brief carries a ``<tool>_invalid:`` mark, which S1.2 no longer files);
``repair_captain``; ``other_captain``.

``--registered-ids`` names the tool ids that exist on the vessel. It is read only for a non-``mcp:`` id the table does
not list: an id in it is critical, the Captain's. A listed id is taken as registered; an ``mcp:`` id is critical.

Offline limits: no tool registry, so a non-``mcp:`` id the table does not list is split only by ``--registered-ids``
and an ``mcp:`` tool is critical; no ontology, so a ``*_chief`` request filed by a chief, or by crew with no
same-department chief, goes live to the First Officer under a live delegation, else the Captain; the recovery-read test
does not check the workspace root. Exit 0 with a receipt; 2, with no receipt written, when the copy is missing, an
argument is invalid, an epoch is not finite, or ``--receipt`` names the copy or one of its SQLite sidecars. A copy that
changes while it is read raises.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from probos.capability_request import agent_work_call, repair_action, validate_action_payload
from probos.config_models.experience import ApprovalInboxConfig
from probos.execution.workspace_results import is_workspace_result_path
from probos.tools.effect_tiers import (
    DECIDER_AUTO,
    DECIDER_CAPTAIN,
    DECIDER_CHIEF,
    ELEVATED_TOOL_IDS,
    ROUTINE_TOOL_IDS,
    TIER_CRITICAL,
    tier_decider,
    tool_tier,
)
from probos.tools.protocol import is_caller_input_error

DEFAULT_RECEIPT = Path("logs/gates/ad-1356-replay.receipt.json")
_DECIDERS = (DECIDER_AUTO, DECIDER_CHIEF, DECIDER_CAPTAIN)
_INPUT_MARK = re.compile(r"\b([a-z0-9_]+)_invalid:[a-z0-9_]+")
_ROWS = (
    "SELECT id, agent_id, kind, work_item_id, created_at, payload FROM capability_requests "
    "WHERE kind = 'action' AND created_at >= ? AND created_at < ? ORDER BY created_at, id"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recovery_read(tool_id: str, params: dict[str, Any]) -> bool:
    """S1.3's test without the workspace root: a read_file of an absolute path with no ``..`` naming the result
    directory."""
    raw = params.get("path") if tool_id == "read_file" else None
    if type(raw) is not str:
        return False
    path = Path(raw)
    return path.is_absolute() and ".." not in path.parts and is_workspace_result_path(path)


def bucket(
    req: Any, *, reads_confined: bool, routine: str, elevated: str, registered: frozenset[str] | None = None,
) -> tuple[str, str]:
    """``(bucket, tool id)`` for one ``action`` request; ``registered`` is ``--registered-ids``, None when absent."""
    call = agent_work_call(req)
    if call is not None:
        tool_id = call["tool_id"]
        if _recovery_read(tool_id, call["params"]):
            return "recovery_read", tool_id
        if tool_id not in ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS and not tool_id.startswith("mcp:"):
            if registered is None:
                return "unlisted", tool_id
            if tool_id not in registered:
                return "unregistered", tool_id
        tier = TIER_CRITICAL if tool_id.startswith("mcp:") else tool_tier(tool_id, reads_confined=reads_confined)
        return f"{tier}_{tier_decider(tier, routine=routine, elevated=elevated)}", tool_id
    payload = req.payload if isinstance(req.payload, dict) else {}
    tool_id = str(payload.get("tool_id", ""))
    if repair_action(req) is not None:
        match = _INPUT_MARK.search(str(payload["params"].get("brief", "")))
        if match is not None and is_caller_input_error(match.group(1), match.group(0)):
            return "input_error", tool_id
        return "repair_captain", tool_id
    return "other_captain", tool_id


def replay(
    db: Path, *, since: float, until: float, reads_confined: bool, routine: str, elevated: str,
    registered: frozenset[str] | None = None,
) -> dict[str, Any]:
    """The receipt for the ``action`` requests in ``[since, until)``; the copy's bytes are hashed before and after."""
    before = _sha256(db)
    with contextlib.closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute(_ROWS, (since, until)).fetchall()
    if _sha256(db) != before:
        raise RuntimeError("replay_approval_tiers: the database copy changed while it was read")
    entries: list[dict[str, Any]] = []
    for request_id, agent_id, kind, work_item_id, created_at, raw in rows:
        try:
            payload = validate_action_payload(json.loads(raw)) if raw else None
        except ValueError:
            payload = None
        req = SimpleNamespace(kind=kind, payload=payload, work_item_id=work_item_id)
        name, tool_id = bucket(
            req, reads_confined=reads_confined, routine=routine, elevated=elevated, registered=registered,
        )
        entries.append({"id": request_id, "agent_id": agent_id, "created_at": created_at, "tool_id": tool_id, "bucket": name})
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["bucket"]] = counts.get(entry["bucket"], 0) + 1
    return {
        "v": 1, "ad": "AD-1356", "db": str(db), "db_sha256": before, "since": since, "until": until,
        "reads_confined": reads_confined,
        "registered_ids": None if registered is None else sorted(registered),
        "deciders": {"routine": routine, "elevated": elevated, "critical": DECIDER_CAPTAIN},
        "requests": len(entries), "counts": dict(sorted(counts.items())),
        "captain_routed": sum(n for name, n in counts.items() if name.endswith("_captain")),
        "chain_decided": sum(n for name, n in counts.items() if name.endswith("_chief")),
        "unlisted_tool_ids": sorted({entry["tool_id"] for entry in entries if entry["bucket"] == "unlisted"}),
        "unregistered_tool_ids": sorted({entry["tool_id"] for entry in entries if entry["bucket"] == "unregistered"}),
        "rows": entries,
    }


def _names_the_copy(receipt: Path, db: Path) -> bool:
    """True when ``receipt`` is the copy or one of its SQLite sidecars: by resolved path (case folded where the host
    folds case) or, when both exist, by file identity (a hard link)."""
    target = os.path.normcase(os.path.realpath(receipt))
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = db.with_name(db.name + suffix)
        if target == os.path.normcase(os.path.realpath(candidate)):
            return True
        if receipt.exists() and candidate.exists() and os.path.samefile(receipt, candidate):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    defaults = ApprovalInboxConfig()
    parser = argparse.ArgumentParser(description="AD-1356: replay filed agent-work approvals, read-only")
    parser.add_argument("--db", required=True, type=Path, help="a COPY of capability_requests.db")
    parser.add_argument("--since", required=True, type=float, help="epoch seconds, inclusive")
    parser.add_argument("--until", required=True, type=float, help="epoch seconds, exclusive")
    parser.add_argument("--reads-unconfined", action="store_true", help="as if security_infra.read_roots were unset")
    parser.add_argument("--routine", choices=_DECIDERS, default=defaults.agent_work_routine_decider)
    parser.add_argument("--elevated", choices=_DECIDERS, default=defaults.agent_work_elevated_decider)
    parser.add_argument(
        "--registered-ids", default=None,
        help="comma-separated tool ids that exist on the vessel; read only for an id the table does not list",
    )
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"replay_approval_tiers: no database at {args.db}", file=sys.stderr)
        return 2
    if not (math.isfinite(args.since) and math.isfinite(args.until)):
        print("replay_approval_tiers: --since and --until must be finite epoch seconds", file=sys.stderr)
        return 2
    if _names_the_copy(args.receipt, args.db):
        print(f"replay_approval_tiers: --receipt {args.receipt} is the copy or one of its sidecars", file=sys.stderr)
        return 2
    reads_confined = not args.reads_unconfined
    registered = (
        None if args.registered_ids is None
        else frozenset(part.strip() for part in args.registered_ids.split(",") if part.strip())
    )
    receipt = replay(
        args.db, since=args.since, until=args.until, reads_confined=reads_confined,
        routine=args.routine, elevated=args.elevated, registered=registered,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"replay_approval_tiers: {receipt['requests']} requests; Captain-routed {receipt['captain_routed']}; "
        f"chain {receipt['chain_decided']}; receipt {args.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**N2-2** `tests/test_ad1356_replay_approval_tiers.py` (new)

```python
"""AD-1356 (#1722) acceptance 1: the replay script on a synthetic copy of 2026-10-31's 28 requests.

The requests are filed by the real ``CapabilityRequestStore``: agent-work payloads from the gate's ``approval_payload``,
and repair payloads in the shape ``repair_action`` recognises; the live database is never opened. On the base this file fails at load (``scripts/replay_approval_tiers.py``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from probos.agent_work_runner import approval_payload
from probos.capability_request import CapabilityRequestStore

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_approval_tiers.py"
PLACEHOLDERS = ("grep_app_placeholder_skip", "grep-app_placeholder_skip", "grep_placeholder_skip")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ad1356_replay", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


replay = _load()


def _repair(code: str) -> dict[str, Any]:
    return {
        "tool_id": "repair", "action": "dispatch",
        "params": {
            "fault_id": f"fault-{code}", "signature": hashlib.sha256(code.encode()).hexdigest(),
            "targets": ["src/probos/substrate/event_log.py"],
            "brief": f"event_log_query failed the same way twice: event_log_query_invalid:{code}",
        },
        "scope_key": "seangalliher/ProbOS", "session_id": None, "thread_id": "t-1",
    }


async def _the_31st(tmp_path: Path) -> Path:
    """28 requests in the 2026-10-31 shape (#1722): 7 codebase_query, 6 list_files, 3 find_mcp_tool, 2 read_file (one a
    recovery read), 1 codebase_read_source, 3 run_python, 3 nonexistent tools, 3 input-error repairs."""
    db = tmp_path / "copy" / "capability_requests.db"
    db.parent.mkdir()
    store = CapabilityRequestStore(db_path=str(db))
    await store.start()
    try:
        item = "wi-replay-1"
        calls: list[tuple[str, dict[str, Any]]] = [("codebase_query", {"concept": f"relay {n}"}) for n in range(7)]
        calls += [("list_files", {"pattern": f"*.{ext}"}) for ext in ("py", "md", "txt", "yaml", "json", "toml")]
        calls += [("find_mcp_tool", {"query": query}) for query in ("grep", "docs", "issues")]
        calls += [
            ("read_file", {"path": str(tmp_path / "project" / "notes.txt")}),
            ("read_file", {"path": str(tmp_path / "workspaces" / ".tool-results" / "r1.txt")}),
            ("codebase_read_source", {"file_path": "src/probos/relay.py"}),
        ]
        calls += [("run_python", {"code": f"print({n})"}) for n in range(3)]
        calls += [(name, {}) for name in PLACEHOLDERS]
        for tool_id, params in calls:
            payload = approval_payload(tool_id, params, item)
            assert await store.file_action_request("forge-1", payload, work_item_id=item) is not None, tool_id
        for code in ("window", "filter_required", "aggregate_filters"):
            assert await store.file_action_request("system", _repair(code)) is not None
    finally:
        await store.stop()
    return db


def _run(db: Path, receipt: Path, *extra: str) -> dict[str, Any]:
    argv = ["--db", str(db), "--since", "0", "--until", str(time.time() + 60), "--receipt", str(receipt), *extra]
    assert replay.main(argv) == 0
    return json.loads(receipt.read_text(encoding="utf-8"))


# R1
async def test_the_31st_replays_to_three_captain_decisions_and_the_copy_is_unchanged(tmp_path: Path) -> None:
    """With read_roots set, the default deciders and run_python registered: 9 routine reads run directly, the
    recovery read is admitted, 9 elevated calls go to AD-1213's route, the 3 nonexistent tools are refused, the 3
    input-error repairs are not filed, and the 3 run_python calls are the Captain's. The copy's bytes do not change."""
    db = await _the_31st(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    got = _run(db, tmp_path / "gates" / "ad-1356-replay.receipt.json", "--registered-ids", "run_python")
    assert got["counts"] == {
        "critical_captain": 3, "elevated_chief": 9, "input_error": 3, "recovery_read": 1, "routine_auto": 9,
        "unregistered": 3,
    }
    assert (got["requests"], got["captain_routed"], got["chain_decided"]) == (28, 3, 9)
    assert got["unregistered_tool_ids"] == sorted(PLACEHOLDERS) and got["unlisted_tool_ids"] == []
    assert got["registered_ids"] == ["run_python"]
    assert got["deciders"] == {"routine": "auto", "elevated": "chief", "critical": "captain"}
    assert got["reads_confined"] is True
    assert got["db_sha256"] == before == hashlib.sha256(db.read_bytes()).hexdigest()


# R2
async def test_with_reads_unconfined_the_two_path_reads_go_to_the_captain_and_a_missing_copy_is_refused(
    tmp_path: Path,
) -> None:
    """With read_roots unset and run_python registered, read_file and codebase_read_source are critical (5 for the
    Captain); the recovery read is still admitted. A missing copy exits 2 and writes no receipt."""
    db = await _the_31st(tmp_path)
    got = _run(db, tmp_path / "receipt.json", "--reads-unconfined", "--registered-ids", "run_python")
    assert (got["counts"]["critical_captain"], got["counts"]["recovery_read"], got["counts"]["routine_auto"]) == (5, 1, 7)
    assert got["captain_routed"] == 5 and got["reads_confined"] is False
    absent = tmp_path / "r2.json"
    assert replay.main(["--db", str(tmp_path / "absent.db"), "--since", "0", "--until", "1", "--receipt", str(absent)]) == 2
    assert not absent.exists()


# R3
async def test_without_registered_ids_run_python_and_the_nonexistent_tools_stay_unlisted(tmp_path: Path) -> None:
    """With no --registered-ids the script cannot tell run_python (registered, critical) from the 3 nonexistent tools
    (refused): all 6 are unlisted, and none is counted for the Captain."""
    db = await _the_31st(tmp_path)
    got = _run(db, tmp_path / "receipt.json")
    assert (got["counts"]["unlisted"], got["captain_routed"]) == (6, 0)
    assert "critical_captain" not in got["counts"] and "unregistered" not in got["counts"]
    assert got["unlisted_tool_ids"] == sorted((*PLACEHOLDERS, "run_python"))
    assert got["unregistered_tool_ids"] == [] and got["registered_ids"] is None


# R4
async def test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write(
    tmp_path: Path,
) -> None:
    """--receipt naming the copy or one of its SQLite sidecars (by another spelling of the path, or as a second
    hard-link name for the copy), and a --since or --until that is not finite, exit 2 and write nothing: the copy's
    bytes and its directory's listing do not change."""
    db = await _the_31st(tmp_path)
    linked = db.with_name("linked.db")
    os.link(db, linked)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    listing = sorted(path.name for path in db.parent.iterdir())
    window = ["--since", "0", "--until", str(time.time() + 60)]
    respelled = db.parent / ".." / db.parent.name / db.name
    respelled_sidecar = db.parent / ".." / db.parent.name / (db.name + "-wal")
    sidecars = [db.with_name(db.name + suffix) for suffix in ("-wal", "-shm", "-journal")]
    for named in (db, respelled, linked, *sidecars, respelled_sidecar):
        assert replay.main(["--db", str(db), *window, "--receipt", str(named)]) == 2, named
    refused = tmp_path / "non-finite.json"
    for since, until in (("nan", "1"), ("0", "nan"), ("inf", "1"), ("0", "inf")):
        argv = ["--db", str(db), "--since", since, "--until", until, "--receipt", str(refused)]
        assert replay.main(argv) == 2, (since, until)
    assert not refused.exists()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in db.parent.iterdir()) == listing
```

## 8. Tracking (M3's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`; note that `OPEN` is one) in its first 120 characters.
**Date rule:** both heads carry 2026-11-02. If M3 is committed on a later date (`git log -1 --format=%cs`), the Builder puts that date in both heads.

**P3-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1356 S3 and S4 (2026-11-02), #1722 -- elevated agent-work calls go to the chain of command; the Captain sets who decides each tier.** `classify_capability_request` classifies an agent-work call (`agent_work_call`) by the tool-effect table, never by `derive_tool_permission`: `filed_call_tier` gives its tier when it is decided (a filed `read_file` or `codebase_read_source` is critical whatever `read_roots` says now; an `mcp:` tool takes AD-1019b's risk from its live registration, `McpToolRisk.OPEN` elevated and the rest critical), and `tier_decider` names its decider from `approval_inbox.agent_work_routine_decider` (default `auto`) and `agent_work_elevated_decider` (default `chief`), two of three new fields; the third, `agent_work_critical_decider`, accepts only `captain` and no decision reads it. A decider of `auto` or `chief` makes the call non-destructive, so AD-1213 decides it as before (a chief at the first hop in the requester's department, the First Officer under a live delegation after the grace period, otherwise the Captain); `captain` and critical stay `CAPTAIN_RESERVED`, as do repair and every other action. `ToolCallConfinement` accepts an empty set. The filed-call refusals, the parked reason and the filed rationale no longer say the Captain decides. With `delegated_approvals_enabled` off every request still goes to the Captain. `scripts/replay_approval_tiers.py` replays a copy of `capability_requests.db`, read-only, to a receipt; `--registered-ids` tells it which unlisted tool ids exist on the vessel. The docstrings and design-doc lines that said every `action` request is the Captain's now name the requests that are. The contract is `prompts/ad-1356-s3-s4-chain-of-command-and-who-decides.md`.

```

**P3-2** `DECISIONS.md` (anchor: BF-947's heading; S3 and S4's entry lands after S2's, before BF-947's)

SEARCH:
```
### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```
REPLACE:
```
### AD-1356 S3 and S4 -- The chain of command decides elevated agent work; the Captain sets who decides each tier (2026-11-02, #1722)

- *Scope.* `tools/effect_tiers.py` (the decider names, `tier_decider`, `direct_tool_ids`, `mcp_tool_tier`, `filed_call_tier`; its docstrings), `delegated_approvals.py` (`classify_capability_request`, `_capability_class`, the service's two classification calls, the module docstring), `agentic_dispatch.py` (`ToolCallConfinement` accepts an empty set; two refusal texts; comments, a docstring and a log message), `agent_work_runner.py` (`_run`, `BLOCKED_REASON`, the rationale, the module docstring), `config_models/experience.py` (three fields; the `ApprovalInboxConfig` docstring), `scripts/replay_approval_tiers.py`, the sentences that said every action is the Captain's (`command_approvals.py`, `repair_approval.py`, `self-maintenance-architecture.md`, the module docstring of `tests/test_ad1213_delegated_approvals.py`), the regenerated `config-facade-baseline.yaml` and `config-reference.md`, and tests. Contract `prompts/ad-1356-s3-s4-chain-of-command-and-who-decides.md`.
- *Classification.* An agent-work call's tier is read when it is decided. A filed path read is critical whatever the roots say now. An `mcp:` tool takes AD-1019b's risk from its live registration (OPEN elevated; CONFIRM, CONSENSUS, unregistered, disabled or unreadable critical). A decider of `auto` or `chief` is non-destructive; `captain`, critical and an unpassed setting are `CAPTAIN_RESERVED`. AD-1213 Q1 is lifted for these calls only (the Captain, 2026-10-31); repair and every other action stay with the Captain.
- *Settings.* `approval_inbox.agent_work_routine_decider` (`auto`), `agent_work_elevated_decider` (`chief`), `agent_work_critical_decider` (only `captain`; no decision reads it). Read at each run's start and inside the decision lock; a `POST /api/config` change applies at restart.
- *Audit.* Unchanged: AD-1213's entry precedes every delegated commit, the Captain is notified of each (pre-clearance refuses `action`), and no standing rule exists for agent work.
- *Rejected.* Recording the tier in the payload (DD-1's persisted six keys); reading live roots at decision; the fields in `agent_work` (a second settings provider); no critical field (unknown keys are ignored); keeping the non-empty set and fixing routine at `auto`; a push to chiefs (AD-1213 DP-1).
- *Residual.* Recorded limits L1 to L11 of the contract.
- *Reversal.* Revert the AD-1356 S3 and S4 commits; a `system.yaml` holding the three fields then loads with them ignored.

### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (its Bug Tracker is for BFs).

## 9. What this does NOT change

- AD-1213 routing (`authority_route`, `evaluate`), the decision lock, audit entry shape (17 keys), notification, fulfilment, `_wire_delegated_approvals`, the review tool, AD-1214 pre-clearance.
- The action payload (DD-1), `agent_work_call`, `repair_action`, request kinds, `EventType`, every database schema.
- The gate (`_gate_for`) order, `_recovery_read`, `CarriedResults`, BF-947's park and admission, S1.1's refusal, plan mode, `task_text`.
- Repair-dispatch authority, `ActionRiskRegistry`, standing rules, S4's "Approve for N hours", the earned-agency bar, S5.
- `security/file_access.py`, the swe_harness tools, the MCP invoke-time gates (`_McpTool.invoke`).
- The live vessel's config and data.

## 10. Mutation rows (one campaign of record: RY-1 to RY-15 on M1's head, RY-16 to RY-26 on the head that holds N2-1 and N2-2 as amended by review rounds 1 and 2)

The Line cells hold the source line without its leading indentation. Prefix `RY` (scoped to this contract).

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| RY-1 | `src/probos/tools/effect_tiers.py` | `return TIER_ELEVATED if risk is McpToolRisk.OPEN else TIER_CRITICAL` | `return TIER_ELEVATED` | `test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk[confirm]` |
| RY-2 | `src/probos/tools/effect_tiers.py` | `return tool_tier(tool_id, reads_confined=False)` | `return tool_tier(tool_id, reads_confined=True)` | `test_a_filed_path_read_stays_with_the_captain_after_read_roots_are_set` |
| RY-3 | `src/probos/tools/effect_tiers.py` | `return mcp_tool_tier(registration.tool.effective_risk())` | `return TIER_ELEVATED` | `test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk[confirm]` |
| RY-4 | `src/probos/tools/effect_tiers.py` | `if type(tier) is not str or tier not in (TIER_ROUTINE, TIER_ELEVATED):` | `if False:` | `test_a_critical_call_stays_with_the_captain_under_the_most_permissive_settings` |
| RY-5 | `src/probos/tools/effect_tiers.py` | `return chosen if type(chosen) is str and chosen in _DELEGABLE else DECIDER_CAPTAIN` | `return chosen if type(chosen) is str and chosen in _DELEGABLE else DECIDER_CHIEF` | `test_with_routine_and_elevated_set_to_captain_a_routine_call_is_filed_and_only_the_captain_decides` |
| RY-6 | `src/probos/tools/effect_tiers.py` | `== DECIDER_AUTO` | `!= DECIDER_CAPTAIN` | `test_with_routine_set_to_chief_a_routine_call_is_filed_and_the_chief_decides_it` |
| RY-7 | `src/probos/tools/effect_tiers.py` | `if type(tool_id) is not str or not tool_id.startswith("mcp:"):` | `if True:` | `test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk[open]` |
| RY-8 | `src/probos/delegated_approvals.py` | `return RequestClass.CAPTAIN_RESERVED if decider == DECIDER_CAPTAIN else RequestClass.NON_DESTRUCTIVE` | `return RequestClass.CAPTAIN_RESERVED` | `test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it` |
| RY-9 | `src/probos/delegated_approvals.py` | `if agent_work_call(req) is None:` | `if True:` | `test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it` |
| RY-10 | `src/probos/agent_work_runner.py` | `routine=inbox.agent_work_routine_decider, elevated=inbox.agent_work_elevated_decider,` | `routine="auto", elevated=inbox.agent_work_elevated_decider,` | `test_with_routine_and_elevated_set_to_captain_a_routine_call_is_filed_and_only_the_captain_decides` |
| RY-11 | `src/probos/agent_work_runner.py` | `routine=inbox.agent_work_routine_decider, elevated=inbox.agent_work_elevated_decider,` | `routine=inbox.agent_work_routine_decider, elevated="chief",` | `test_with_elevated_set_to_auto_list_files_runs_with_nothing_filed` |
| RY-12 | `src/probos/cognitive/agentic_dispatch.py` | `type(self.tool_ids) is not frozenset` | `type(self.tool_ids) is not frozenset or not self.tool_ids` | `test_with_routine_and_elevated_set_to_captain_a_routine_call_is_filed_and_only_the_captain_decides` |
| RY-13 | `src/probos/config_models/experience.py` | `agent_work_critical_decider: Literal["captain"] = Field(` | `agent_work_critical_decider: Literal["auto", "chief", "captain"] = Field(` | `test_critical_is_the_captains_under_every_setting_and_no_config_value_moves_it` |
| RY-14 | `src/probos/cognitive/agentic_dispatch.py` | `"That call needs approval before it runs. It was filed for review and did not run. Do not repeat it: a "` | `"That call needs the Captain's approval before it runs. It was filed for review and did not run. Do not repeat it: a "` | `test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it` |
| RY-15 | `src/probos/agent_work_runner.py` | `BLOCKED_REASON: Final = "waiting for a decision on a tool call this work filed for approval"` | `BLOCKED_REASON: Final = "waiting for the Captain's decision on a tool call outside the read-only set"` | `test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it` |
| RY-16 | `scripts/replay_approval_tiers.py` | `if tool_id not in ROUTINE_TOOL_IDS \| ELEVATED_TOOL_IDS and not tool_id.startswith("mcp:"):` | `if False:` | `test_the_31st_replays_to_three_captain_decisions_and_the_copy_is_unchanged` |
| RY-17 | `scripts/replay_approval_tiers.py` | `if match is not None and is_caller_input_error(match.group(1), match.group(0)):` | `if False:` | `test_the_31st_replays_to_three_captain_decisions_and_the_copy_is_unchanged` |
| RY-18 | `scripts/replay_approval_tiers.py` | `reads_confined = not args.reads_unconfined` | `reads_confined = True` | `test_with_reads_unconfined_the_two_path_reads_go_to_the_captain_and_a_missing_copy_is_refused` |
| RY-19 | `scripts/replay_approval_tiers.py` | `if tool_id not in registered:` | `if False:` | `test_the_31st_replays_to_three_captain_decisions_and_the_copy_is_unchanged` |
| RY-20 | `scripts/replay_approval_tiers.py` | `if registered is None:` | `if False:` | `test_without_registered_ids_run_python_and_the_nonexistent_tools_stay_unlisted` |
| RY-21 | `scripts/replay_approval_tiers.py` | `if _names_the_copy(args.receipt, args.db):` | `if False:` | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` |
| RY-22 | `scripts/replay_approval_tiers.py` | `for suffix in ("", "-wal", "-shm", "-journal"):` | `for suffix in ("",):` | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` |
| RY-23 | `scripts/replay_approval_tiers.py` | `target = os.path.normcase(os.path.realpath(receipt))` | `target = str(receipt)` | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` |
| RY-24 | `scripts/replay_approval_tiers.py` | `if not (math.isfinite(args.since) and math.isfinite(args.until)):` | `if False:` | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` |
| RY-25 | `scripts/replay_approval_tiers.py` | `if not (math.isfinite(args.since) and math.isfinite(args.until)):` | `if not math.isfinite(args.since):` | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` |
| RY-26 | `scripts/replay_approval_tiers.py` | `if receipt.exists() and candidate.exists() and os.path.samefile(receipt, candidate):` | `if False:` | `test_a_receipt_that_names_the_copy_or_its_sidecars_and_a_non_finite_epoch_are_refused_before_a_write` |

Each row is killed by the test in its last column. RY-1 to RY-20 were killed by their named killers on the oracle built on S2's frozen head (§12, third re-run), and again on A3's oracle (§12, fourth re-run; A3 renamed WD2, the killer of RY-5, RY-10 and RY-12). On the oracle of amendment R1 (§12, fifth re-run) RY-16 to RY-25 were each killed by their named killer, and on the oracle of amendment R2 (§12, sixth re-run) RY-16 to RY-26.

Not mutated: `filed_call_tier`'s guard (`registration is None ...`). CC5[reaped] reaches it. With the guard removed, the reaped id's `None` registration raises inside the `try` and the `except` answers critical too, so a mutant of either survives: the two fail closed together. The P1-19 rationale text is asserted by CC1 but not mutated, because RY-14 and RY-15 cover the text set.

**Campaign of record.** After an unmutated baseline of N1-1, N1-2, N2-2 and the five edited test files, run each row against the file that holds its killer. Record the base tree and the sha256 of each mutated file.

## 11. Recorded limits

- **L1.** Chiefs pull. A chief decides only by calling `review_requests` in their own turn, after the Captain grants it (AD-1213's "How an agent decides" paragraph in `DECISIONS.md`); nothing pushes a request to them. The rollout live check counts chief decisions (D7).
- **L2.** A filed path read is always the Captain's. Under `routine: chief`, a filed `read_file` or `codebase_read_source` still goes to the Captain.
- **L3.** MCP risk is read at decision from the live registration. A tool the idle reaper has unregistered is critical. Under `elevated: auto` an OPEN `mcp:` call is still filed (the direct set is built from the table, which lists no `mcp:` id) and goes to the chain. The invoke-time CONFIRM and CONSENSUS gates stay beneath.
- **L4.** The settings are read at run start (the direct set) and at each decision. A `POST /api/config` change persists and applies at restart (no section-registry `hot_reload` entry). A run that started before the change keeps its set.
- **L5.** S2's "Routine reads run directly." in `task_text` is incomplete under `elevated: auto` and false under a non-`auto` routine. The per-call refusal text is accurate.
- **L6.** Routing is AD-1213's. A chief's own request, or one from a post with no same-department chief at the first hop, goes to the First Officer under a live delegation, else the Captain. `chief_security` has `authority_over: []` (`config/ontology/organization.yaml:324`), so no Security request reaches Worf.
- **L7.** The replay's offline limits: no registry (a non-`mcp:` id the table does not list is split only by the operator's `--registered-ids`, which the script takes on trust; a listed id is taken as registered; `mcp:` is critical), no ontology (a `*_chief` request from a chief goes live to the First Officer under a live delegation, else the Captain), input-error repairs are recognised from the brief text, and the recovery-read test does not check the root.
- **L8.** The new `BLOCKED_REASON` and rationale apply to newly filed and parked items. Existing rows keep the old text.
- **L9.** The Captain is notified of every delegated decision (AD-1214 pre-clearance refuses `action`), roughly one notification per elevated request.
- **L10.** `list_files` stays elevated until BF-948 (#1736) puts it under the read policy (S2 L4).
- **L11.** `run_python` stays critical until a later decision (Q3).

## 12. Verified Against Codebase (2026-11-02, on `f0c935a1`)

```
Read delegated_approvals.py :1-330 (12-15 floor; 39-50 imports; 162-165 ToolLookup; 168-204 classify; 244-297 evaluate),
  :400-1000 (467-499 _audit_detail 17 keys; 519-553 __init__; 555-565 enabled; 573-728 decide, 607-608 NOT_ENABLED,
  615-616 audit required, 670-675 entry before commit, 719 fulfil; 730-778 list_reviewable; 780-810 record_captain_decision
  792-796 classify; 860-894 _verdict, 866-872 settings and classify; 930-970 notify; 972-990 _fulfilled)
grep classify_capability_request src -> delegated_approvals.py:168, :794, :871; routers/capability_requests.py:375
Read routers/capability_requests.py :360-377 (_approval_admits_design, DESTRUCTIVE only), :425-509 (487-500
  agent_work_approval mark_fulfilled), :537 fulfil_on_approval alias, :608-629 (624 no standing rule for agent work)
Read startup/finalize.py :3322-3410 (3331 flag; 3377-3390 service; 3383 tool_registry; 3388 settings lambda)
Read capability_request.py :77-78 regexes, :89-107 schema, :118-147 repair_action, :150-176 agent_work_call,
  :193-229 validate_action_payload, :555-582 rows, :807-867 file_action_request
Read agent_work_runner.py :1-200 (13-16 docstring S2; 63 import S2; 72 APPROVAL_ACTION; 78 APPROVAL_USE_PREFIX;
  86 BLOCKED_REASON; 168-176 approval_payload; 179-191 _recovery_read S1), :209-232 task_text (228 S2 sentence),
  :505-738 (578-671 _run; 604-615 confinement S2; 689-738 _gate_for; 728-731 rationale)
git blame agent_work_runner.py -L 86 -L 726,731 -L 609,615 -> 86, 726-731 b8abdfee (AD-1347); 609-613 4d9a0f76 (S2)
Read tools/effect_tiers.py (whole, S2)
Read cognitive/agentic_dispatch.py :296-375 (301-304 S1 comment; 305-313 texts; 331-334 _NEVER_RAN; 337-375
  ToolCallConfinement, 354 non-empty), :820-857 (843-856 S1.1 then confinement), :1665-1835 (_McpTool; 1717-1719
  tool_id; 1741-1760 effective_risk; 1809 OPEN identity), :2120-2163 (2128 type(tool) is _McpTool; 2153 by name),
  :2966-2975, :3073-3084
git blame agentic_dispatch.py -L 301,313 -L 339,346 -L 352,359 -> 301-303 2e5fe70b (S1); 305-313, 352-359 b8abdfee
grep "\.tool_ids\b|tool_call_confinement_invalid" src tests -> agentic_dispatch.py:354,:848,:2975;
  test_ad1347_s3_execution.py:576,:578; test_bf947_confinement_answer.py:64 (record not callable)
Read cognitive/mcp_workbench.py :700-793 (751 tool_id; 764-785 _McpTool registered in ToolRegistry)
Read integrations/mcp_bridge/risk.py (whole; 34-39 McpToolRisk); grep mcp_bridge/__init__.py -> 8-12 heavy imports
Read tools/protocol.py :94-106 is_caller_input_error; grep tools/protocol.py -> 234-247 ToolRegistration tool, enabled
grep tools/registry.py -> 199 unregister; 206 get
Read decision_pre_clearance.py :176-205 (188-194 refuses kinds); grep -> :82 kind CHECK
Read config_models/experience.py :1-40, :215-296 (233-244 delegated_approvals_enabled; 289-296 last field)
grep config.py -> 3584 AgentWorkConfig; 3906 SystemConfig (no extra=); 4020 approval_inbox
Read routers/config.py :1-60, :217-341 (248-260 422; 286-294 restart_required); grep settings/ approval_inbox -> 0
Read tests/test_ad1347_s3_execution.py :1-290 (rig), :369-415, :560-580 (575-577 pin), :645-674
Read tests/test_ad1347_s1_agent_work.py :57-76 (CREW, WIRED); config/ontology/organization.yaml :28-39, :105-136,
  :320-324, :375-409 (builder->builder_officer->chief_engineer; diagnostician->chief_medical; architect->first_officer)
Read tests/test_ad1213_delegated_approvals.py :213-240, :286-374, :480-600 (577-583 every-action test: browser,
  redirect, repair only), :925-949 (index-relative); tests/test_ad1214_decision_pre_clearance_store.py :688-707
Read tests/test_ad1270e2c_experience_models.py :60-101, :255-345 (exact dumps); tests/test_ad1152_agentic_correlation.py
  :238-246, :285-311; docs/development/config-facade-baseline.yaml :1-56, :481-494; scripts/check_config_facade.py :1708-1739
grep gen_config_reference -> tests/test_config_reference_current.py; scripts/gen_config_reference.py :10-12
Read tests/test_ad741_config_api.py :1-116; tests/test_ad864_crew_assignment.py :86-93; substrate/agent.py :41-43 pool
Read swe_harness/tools.py :1374-1385 read_perms; execution/workspace_results.py :27, :428-430
Read scripts/check_architecture_principles.py :40-94, 155, 187-188 (500 lines, 15 methods); gen_ad_ledger.py :124-132
Read DECISIONS.md :10992, :11460-11470; grep "^### (AD-1356 S[12]|BF-947)" -> 1244, 1256, 1270; PROGRESS.md :1-6
```

**Re-run (2026-11-02), the orchestrator's oracle; amendment A1 answers it.** On S2's pre-repair head `5d5072ba` every pair applied. On S2's repaired head `06dd7539` P1-2 did not match (S2's round 1 deleted a clause; A1 re-anchored it) and every other pair applied. On the oracle's M1: RY-1 to RY-15 were killed, each by its named killer (baseline of the then three edited test files, N1-1 and N1-2: 220 passed); the three items under "Not verified" held; CC1 to CC6 and WD1 to WD4 passed; the §13 scripts passed (config facade 1883 fields). G1: 697 passed, 1 failed (`tests/test_ad1270e1_config_facade.py:1569`, `assert 1883 == 1880`; A1 adds P1-24). G2 on the oracle's M2: R1 failed (`{'unlisted': 6} != {'unlisted': 3}`, no `critical_captain`) and R2 failed (`critical_captain` 2, not 5), because `bucket` could not tell `run_python` from the nonexistent ids (A1 adds `--registered-ids`, R3, RY-19 and RY-20).

**Re-run of the amended contract (2026-11-02), the orchestrator's oracle.** On the oracle built on `06dd7539` (A1's base; it differs from S2's frozen head `bfb6b72d` by `routine_tool_ids`'s docstring line and by prose: S2's contract, its `DECISIONS.md` campaign bullet and the Cursor row of `docs/research/reference-projects.md`): G1 698 passed (17 files); the four check scripts exit 0 (config facade 1883 fields); G2 3 passed (R1, R2, R3); RY-1 to RY-15 were killed, each by its named killer (baseline 480 passed over seven test files: N1-1, N1-2 and the five edited ones), and RY-16 to RY-20 by theirs (baseline 3 passed: N2-2); 0 census problems. On S2's frozen head `bfb6b72d` (review round 3 READY) only the pair application was re-run: 30 of 31 pairs applied, P1-2 among them; P1-3 did not match, because S2's round-2 repair shortened `routine_tool_ids`'s docstring, and A2 re-anchors it. G1, G2 and the census are not yet measured on the frozen head.

**Re-run on S2's frozen head (2026-11-02), the orchestrator's oracle; amendment A3 follows it.** On S2's frozen head (main `b773c662` has the same tree; the scratch base `847ce0b1` adds only this file), the 31 pairs and the four new files applied with 0 failures. G1: 698 passed (17 files). G2: 3 passed. The four check scripts exit 0 (config facade fields=1883). RY-1 to RY-20 were each killed by their named killer. A3 then changed text only: new pairs P1-32 to P1-34 (comments and a log message); text in P1-3, P1-14, P1-18, P1-20, P1-21, P1-23, N1-1, N1-2, N2-1, N2-2, P3-1 and P3-2; CC6 and WD2 renamed. The oracle re-runs on A3.

**Re-run of A3 (2026-11-02), the orchestrator's oracle.** On main `b773c662` (the scratch base `96184b14`): the 34 pairs, the four new files and the two regenerated files applied with 0 failures; G1: 698 passed (17 files); G2: 3 passed; the four check scripts exit 0 (config facade fields=1883); RY-1 to RY-15 were each killed by their named killer (baseline 480 passed over seven test files) and RY-16 to RY-20 by theirs (baseline 3 passed); 0 census problems. On main `f31afa56` (BF-946 merged) the same pairs applied again with 0 failures and G1 and G2 gave the same counts; every file M1 and M2 touch has the same blob in the two oracles, so the census is not repeated.

**Re-run of amendment R1 (2026-11-03), the orchestrator's oracle.** On main `f31afa56` (the scratch base `6c52febd`): the 34 pairs, the four new files and the two regenerated files applied with 0 failures. Against the oracle of the contract as committed before R1, M1's stage differs only by this file (the M1 blobs are unchanged), M2's stage by this file, N2-1 and N2-2, and the tracker stage also by `PROGRESS.md` (P3-1). G2: 4 passed (R1 to R4). RY-16 to RY-25 were each killed by their named killer (baseline 4 passed); 0 census problems. A probe against the base script (M2 as first committed) and the repaired one: on the base script `--receipt` naming the copy overwrote it with the JSON receipt (exit 0, and the copy was then not a database) and `--since nan` wrote a receipt holding `NaN`, which a strict JSON parser rejects; the repaired script exits 2 for the first and for `nan` or `inf` in either epoch, and writes nothing. A copy whose rows hold a `created_at` of plus or minus infinity or of text is read through a finite window without selecting them, and the receipt parses strictly: the receipt holds no non-finite float once the epochs are finite, so a serialization guard (`allow_nan=False`) would be unreachable and is not added.

**Re-run of amendment R2 (2026-11-03), the orchestrator's oracle.** On main `f31afa56` (the scratch base `795daffc`): the 34 pairs, the four new files and the two regenerated files applied with 0 failures. Against the oracle of amendment R1, M1's stage differs only by this file, and M2's stage and the tracker stage by this file, N2-1 and N2-2 (`PROGRESS.md` is unchanged). G2: 4 passed (R1 to R4). RY-16 to RY-26 were each killed by their named killer (baseline 4 passed); 0 census problems. A probe against the script of amendment R1 and the amended one: on the former a second hard-link name for the copy, given as `--receipt`, overwrote the copy (exit 0, and the copy was then not a database). The amended script exits 2 for that name, for a hard link in another directory and for relative spellings of the copy and the link, with the copy's bytes and its directory's listing unchanged; it still writes a receipt to an ordinary path and still overwrites an existing file that is not the copy.

## Absence Verified (2026-11-02, on `f0c935a1`)

```
A1 CLAIM: no src code other than delegated_approvals.py and routers/capability_requests.py calls classify_capability_request.
   RUN:   Grep "classify_capability_request" src/probos
   FOUND: delegated_approvals.py:168 (def), :794, :871; routers/capability_requests.py:375 (tool_registry=None; reads DESTRUCTIVE only)
   HOLDS: yes; new keyword parameters default to None; :375 sees CAPTAIN_RESERVED for agent work as before
A2 CLAIM: only agent_work_runner.py constructs ToolCallConfinement in src, and only test_ad1347_s3_execution.py:575 pins an empty set.
   RUN:   Grep "ToolCallConfinement\(" src; Grep "\.tool_ids\b|tool_call_confinement_invalid" src tests (on f0c935a1);
          Grep "ToolCallConfinement\(|replace\(.*confinement|confinement_invalid" src tests (A3, on 847ce0b1: every
          construction, not only the pins)
   FOUND: src: agent_work_runner.py:611 (agentic_dispatch.py:359 and :2975 raise the error; :2975 is the executor's type
          and plan-mode check, which reads no set); tests: test_ad1347_s3_execution.py:561, :569, :577 (the loop at :575 is
          the only empty set), :581, :732; test_ad1356_s1_unknown_tools.py:91; test_bf947_confinement_answer.py:38-65
          (each a non-empty set)
   HOLDS: yes
A3 CLAIM: no .py file and no prompt names the new symbols, fields or script.
   RUN:   Grep "filed_call_tier|tier_decider|direct_tool_ids|mcp_tool_tier|DECIDER_(AUTO|CHIEF|CAPTAIN)|agent_work_(routine|elevated|critical)_decider|replay_approval_tiers" !logs/**
   FOUND: none
   HOLDS: yes
A4 CLAIM: no section-registry descriptor covers approval_inbox or agent_work, so POST /api/config changes need a restart.
   RUN:   Grep "approval_inbox|agent_work" src/probos/settings; Grep "hot_reload" src/probos (A3, on 847ce0b1)
   FOUND: 0; hot_reload is read in settings/section_registry.py, routers/config.py:179, :286-294 (restart unless every
          changed path is a registry field marked hot_reload) and perception/__init__.py; WD4 asserts restart_required
   HOLDS: yes
A5 CLAIM: nothing pushes a reviewable request to a chief.
   RUN:   Grep "review_requests|reviewable" src/probos (files), then the agentic_loop.py hit
   FOUND: review_requests_tool.py, finalize.py, delegated_approvals.py, config_models/experience.py, approval_authority.py,
          swe_harness/agentic_loop.py:2630 (result presentation only);
          A3, on 847ce0b1: Grep "CAPABILITY_REQUEST_\w+" src/probos (every consumer of a request's events):
          capability_request_notifier.py (AD-857: a notice to the Captain's DM channel, wired at finalize.py:3256);
          finalize.py:3171, capability_gap_driver.py, promoted_turn_recovery.py (DECIDED or FULFILLED only);
          event_persistence.py:49-51 (persists)
   HOLDS: yes (L1, D7)
A6 CLAIM: scripts/replay_approval_tiers.py does not exist. RUN: covered by A3. HOLDS: yes
A7 CLAIM: no UI source or other test pins the four changed texts by value.
   RUN:   Grep "outside the read-only set|waiting for the Captain's decision|needs the Captain's approval" ui/src; same in tests, ui/e2e
   FOUND: ui/src none; tests reference CONFINED_CALL_* and BLOCKED_REASON by name; ui/e2e/fixtures/ad1347-agent-work-approvals.json
          and test_ad1347_s3_execution.py:659 hold their own literal rationale (independent of the runner)
   HOLDS: yes
A8 CLAIM: no test reads delegated_approvals.py's source by its name (a `?raw`-style pin of its lines).
   RUN:   Grep "delegated_approvals\.py|getsource\(.*delegated" tests (on f0c935a1); A3, on 847ce0b1: Grep
          "delegated_approvals\.py|effect_tiers\.py|agent_work_runner\.py|agentic_dispatch\.py|experience\.py|command_approvals\.py|repair_approval\.py|self-maintenance-architecture" tests
   FOUND: delegated_approvals.py: tests/fixtures/file_durations.json:199 only (a duration). The other edited files:
          test_ad1270e2c_experience_models.py:38, :533 (in G1); test_ad1299_s2a_approval_chain.py:41 (importers of
          repair_approval; no pair adds one); test_ad1320_agentic_budget_awareness.py:658-662 (files naming
          budget_awareness_state; no pair adds it); test_ad1343_stop_seam_inventory.py:153 and the seam registry (AST, so
          comments are invisible); fixtures/ad1152_agentic_off_golden.json:8 (a capture-time blob id; test_ad1152 is in G1);
          test_ad1126:1150, test_ad1258:1377 (module-file identity)
   HOLDS: for tests that name a file. Not shown by this search: a test that walks every file under src (rglob, os.walk
          or glob("**") occur in 95 test files, e.g. test_layer_boundaries.py:197, whose layer map leaves tools and
          integrations unranked); the broad gate covers those.
A9 CLAIM: F-553 is defined nowhere outside prompts/.
   RUN:   Grep "F-553|F553" !{logs,prompts}/**
   FOUND: none
   HOLDS: yes; §13 names the concrete config consumers instead
A10 CLAIM: the config goldens a new approval_inbox field moves are these, keyed by name or by count.
   RUN:   by name: Grep "decision_pre_clearance_max_ttl_hours" !{logs,prompts}/** (on f0c935a1);
          by count: Grep "\b1880\b|field_definitions|fields=1" in tests and in scripts (A1, on 06dd7539)
   FOUND: by name: test_ad1270e2c, test_ad1214_store (index-relative), test_ad1152_agentic_correlation,
          config-reference.md, config-facade-baseline.yaml, DECISIONS.md (history), and src;
          by count: tests/test_ad1270e1_config_facade.py:1569 (its other hits are history comments;
          scripts/check_config_facade.py:1030, :1048, :1073, :1787 compute the count)
   HOLDS: yes; P1-22, P1-23, P1-24 and the two regenerations cover every one. The first draft ran the name search
          only and claimed "exactly these"; G1 found the count-keyed golden (§12, re-run).
A11 CLAIM: outside the contract's other pairs, the sentences S3 makes false by saying every action request is the
          Captain's are exactly P1-25 to P1-31's.
   RUN:   rg -n -i "every .?action|reserves every|Captain-reserved" src docs (the orchestrator);
          Grep -i "Q1|every .?action|action.? request.{0,40}Captain" src/probos;
          Grep "A floor stays|every consensus build" !logs/**;
          Grep -i "captain.reserved|reserved (to|for) the Captain|only the Captain (can|may) (approve|decide)" ui/src;
          Grep "self-maintenance-architecture|reserves every|Captain-reserved,|stays with the Captain alone|keeps every action" tests
   FOUND: command_approvals.py:23-24; repair_approval.py:9-10; self-maintenance-architecture.md:76, :221, :389-390;
          config_models/experience.py:75-76 (wrapped across two lines, which the single-line rg misses);
          tests/test_ad1213_delegated_approvals.py:6; delegated_approvals.py:12, :171 (P1-4, P1-7); ui/src none;
          test_ad1194_unified_capability_triage.py "Captain-reserved" hits are about consensus build cards
   HOLDS: yes; DECISIONS.md and PROGRESS.md entries are dated records and stay
A12 CLAIM: outside the contract's other pairs, the sentences that say an admitted agent-work call runs under the
          Captain's approval are exactly P1-32 to P1-34's.
   RUN:   Grep "runs under the Captain|under the Captain's (single-use )?approval" {src,tests,ui,docs,scripts};
          Grep "Captain's approval|Captain approves|approved by the Captain" in src/probos/agent_work*.py,
          src/probos/tools/*.py, agentic_dispatch.py, capability_request.py, config/standing_orders (A3, on 847ce0b1)
   FOUND: agentic_dispatch.py:110-111, :853-855, :1266-1268 (P1-32 to P1-34); :261, :267, :272 (AD-1154's parked-step
          texts: the request they file carries the browser action, not `agent_work_call`, so it stays Captain-reserved);
          :303, :306, :311, :342 (P1-11 to P1-13); swe_harness/tools.py:1307 (a run_command escalation, still
          Captain-reserved, P1-25); tests, ui and docs: none
   HOLDS: yes
```

**Not verified at drafting; measured by the orchestrator's oracle on 2026-11-02 (§12, re-run), and all three hold:**
- CC5: that the rig's executor invokes an `mcp:` tool registered straight into the `ToolRegistry` (the AD-1241 offer gate at `agentic_dispatch.py:3086-3089` governs presentation; a scripted call by name is assumed to run). If it does not, stop and return to the Architect.
- That `ApprovalAuthorityStore(db_path="")` starts and stops with no file.
- That the DECIDED and FULFILLED events of `service.decide` reach the rig's `request_events` like the Captain route's do (the same `store.decide` and `mark_fulfilled`).

## 13. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`** (scans `src` only, `:155`):
  - `delegated_approvals` → `tools.effect_tiers`, and `effect_tiers` → `integrations.mcp_bridge.risk` (lazy): all unranked, so no layer row.
  - No method is added. `DelegatedApprovalService` lines are net zero (P1-9, P1-10). `AgentWorkRunner`'s span grows by 6 lines (P1-18), 413 to 419 on the oracle's M1, against a trigger above 500. `ToolCallConfinement` gains 1 line (P1-14). P1-32 to P1-34 keep their line counts.
  - No `create_task`; no database connect in `src`. The replay's `sqlite3.connect` is under `scripts/`.
- **`check_dormant_classes.py --check`:** no new class in `src`.
- **Config surface:** the facade baseline and `config-reference.md` are regenerated in M1, after P1-27; P1-22 and P1-23 update the two goldens keyed by name and P1-24 the one keyed by count (A10); `test_ad1213`/`test_ad1214` pins are index-relative and unaffected.
- **`gen_ad_ledger.py --check`:** passes once M3 regenerates. Heads carry no status keyword (no "open") in their first 120 characters.
- **Collection:** three new files under `tests/`, one new script.

## 14. Prior Art and Blind Spots

- **Internal prior work:**
  - AD-1213 (routing, audit before commit, fail-closed lookups, DP-1 pull model): reused unchanged.
  - AD-1214 (pre-clearance refuses `action`): every chief decision still notifies.
  - AD-1019b `McpToolRisk` and AD-1019c `effective_risk()`: the MCP tier, read rather than duplicated.
  - AD-1347 S3 A2 (one call per approval) and Q2: kept.
  - S2's table and its L10/L11: answered by D1 and the replay.
  - AD-1154 DD-1 payload: not widened.
  - `docs/research/tiered-trust-initialization-research.md`: role-based trust tiers, consistent with routing by post; no earned-agency bar (Q4).
- **External:**
  - Tiered approval at the tool call. Armorer Labs classifies each action into a tier at the tool-call boundary, in the runtime and not the agent. Tiers 0 and 1 run with no prompt (tier 1 with a durable receipt and an undo token), tier 2 prompts once per session per class, and tier 3 prompts every time. It warns about "click yes" approval fatigue and about tier inflation ([tiered approval escalation](https://dev.to/armorer_labs/ai-agents-need-tiered-approval-escalation-not-one-big-confirm-button-2id0)). Already present: S2's table classifies in the runtime, and S3 never reads the agent's rationale (D1 option 4); the fatigue risk is L9. Considered, deferred: approving a class of call for a session (a standing rule; none exists for agent work, D5) and tier 1's undo token.
  - Gateway hold. Gravitee holds a matching MCP tool call at the gateway, and records every decision with who made it ([Gravitee HITL](https://www.gravitee.io/platform/hitl/); [docs](https://documentation.gravitee.io/agent-management/4.12/govern/require-human-approval-for-mcp-tool-calls)). Already present: the filed call waits as a request, and AD-1213's audit entry names the decider (D5). Considered, deferred: edit-then-approve, because it would change DD-1's persisted payload.
  - Frameworks. CrewAI's `human_input` flag is set in the task definition, and the agent prompts the user before delivering its final answer ([CrewAI docs](https://docs.crewai.com/v1.15.28/en/learn/human-input-on-execution)). AutoGen 0.2 sets `human_input_mode` on `ConversableAgent`: `NEVER`, `TERMINATE` (the default) or `ALWAYS` ([AutoGen docs](https://microsoft.github.io/autogen/0.2/docs/tutorial/human-in-the-loop/)). ZenML's comparison row reads "Mark a task to pause for human approval" and "Add a `UserProxyAgent` for live human input" ([ZenML](https://www.zenml.io/blog/crewai-vs-autogen)). confirm.dev's CrewAI guide gates a tool with a `BaseTool` subclass whose `_run` calls `require_approval(...)` and blocks until a human decides; the agent sees a denial as the tool's result ([confirm.dev](https://confirm.dev/docs/frameworks/crewai)). ProbOS's gate files the call and parks the item instead of blocking (BF-947). Nothing to absorb.
  - `docs/research/reference-projects.md`, judged on 2026-11-02:
    - AutoGen and CrewAI (last reviewed 2026-09-03; frameworks 180 days, so not overdue) were examined because they are relevant. Row updates for the orchestrator: set *Last reviewed* to 2026-11-02 and *Depth* to `checked`, and append to *Where recorded*. AutoGen: "; AD-1356 S3 and S4 (#1722) Prior Art, `prompts/ad-1356-s3-s4-chain-of-command-and-who-decides.md` (0.2's `human_input_mode` on `ConversableAgent`: NEVER, TERMINATE (the default: input is asked for only when a termination condition is met) or ALWAYS; nothing new)". CrewAI: "; AD-1356 S3 and S4 (#1722) Prior Art, `prompts/ad-1356-s3-s4-chain-of-command-and-who-decides.md` (the task's `human_input` flag: the agent asks before its final answer; confirm.dev's guide gates a tool with a `BaseTool` subclass that calls an approval service; nothing new)".
- **Blind spots found:**
  1. Chiefs only pull (L1, D7): S3 is inert for a department whose chief lacks the grant or never lists.
  2. A filed path read could be widened by a later roots change (D1: closed by construction).
  3. A reaped MCP tool at decision time (L3: fails closed).
  4. Config extra keys are ignored, so "critical fixed" needs a typed field (D2).
  5. `ToolCallConfinement`'s non-empty rule conflicts with `routine: captain` (D2).
  6. Four agent- and HXI-facing texts named the Captain (D6), and three comments and a log message said an admitted call ran under the Captain's approval (P1-32 to P1-34, A12).
  7. Security crew have no chief at hop 1 (L6).
  8. Three config goldens beyond the facade baseline, two keyed by name and one by count (A10).
  9. Offline, a registered tool the table does not list (`run_python`) looks like a nonexistent one (D4, `--registered-ids`).

## 15. Diff Reviewer: properties to verify (run the three new test files and the five edited ones, then the greps)

1. For an `action` request that is not `agent_work_call`, `classify_capability_request` returns `CAPTAIN_RESERVED` under every argument.
2. For an agent-work call: tier critical, or decider `captain` → `CAPTAIN_RESERVED`; decider `auto` or `chief` → `NON_DESTRUCTIVE`; deciders not passed → `CAPTAIN_RESERVED`.
3. `tier_decider(critical, …)` is `captain` for every input, and no decision reads `agent_work_critical_decider`.
4. `filed_call_tier` never reads the roots or the config. On the `mcp:` path a missing, disabled or mismatched registration, or a risk that cannot be read, is critical; a registry or registration that raises propagates, and the service then refuses (`decide`: `STATE_UNREADABLE`; `list_reviewable` skips it). OPEN is matched by identity.
5. `direct_tool_ids` never contains a tool `tool_tier` calls critical, and under the defaults equals `routine_tool_ids`.
6. With `delegated_approvals_enabled` false no one but the Captain decides a filed request (CC6), and wiring is unchanged.
7. `DelegatedApprovalService`'s body line count is unchanged; no class under `src/` gains a method.
8. Every added or rewritten docstring, comment, config description, agent-facing text and test docstring is true of the head.
9. The facade baseline diff touches only `ApprovalInboxConfig`'s three field rows, the `schema_sha256` of `ApprovalInboxConfig` and of `SystemConfig` (which nests it), `surface_counts` and `canonical_dump_sha256`.
10. The replay opens the copy with `mode=ro`, reads `--registered-ids` only for an id the table does not list, exits 2 before writing when `--receipt` names the copy or one of its SQLite sidecars or when an epoch is not finite (R4), and the test never names `%LOCALAPPDATA%`.
11. CC1-CC6 and WD1-WD3 each start from a work item and end at the item finishing or waiting for the Captain.
12. P1-25 to P1-34 change text only, and each changed sentence is true of the head.

## 16. Acceptance criteria

1. CC1: a same-department chief approves an elevated call; the decision is audited and notified; the item resumes and the call runs (#1722 acc. 6, 7, 8).
2. CC2: a chief's own request and another department's chief are refused; the Captain decides (acc. 6).
3. CC3 and WD4: a critical or unlisted call is `CAPTAIN_RESERVED` under the most permissive settings, and no config value, through the model or `POST /api/config`, changes that (acc. 2).
4. CC4, CC5, CC6: a filed path read stays with the Captain; MCP tiers follow AD-1019b; with the flag off a filed elevated call waits for the Captain.
5. WD1-WD3: elevated `auto` runs `list_files` with nothing filed; routine and elevated `captain` (an empty direct set) leaves a filed routine call to the Captain; routine `chief` lets the chief decide a filed routine call.
6. R1 to R3: the replay reports 28 requests, 3 Captain-routed with roots set and `run_python` registered, 3 unregistered, and leaves the copy unchanged (acc. 1); with no `--registered-ids` the 6 unlisted ids stay unlisted; at rollout the orchestrator runs it on a stopped-vessel copy (D4). R4: a receipt that names the copy or one of its sidecars, and a `--since` or `--until` that is not finite, exit 2 and write nothing.
7. Every §10 mutant is killed; G1-G3 and the §13 checks pass; the broad gate's receipt is green.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
