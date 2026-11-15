# BF-982: an agent-work call to an MCP tool is filed, kept and approved under its registered id, not the provider alias

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-15
**Status:** ready to build on `origin/main` `799869715f` (tree `33f1b1b79ce8`). **Owning issue:** #1817. Commits say `Refs #1817.`
**Dependencies:** none. It is the prerequisite of #1796 (BF-965, its section 6, L5) and is built first in the same wave: its own commits, its own reviews, one PR and one broad gate for both. No pair here anchors on a line that #1796's contract (v1p3c) anchors on (section 7.4).
**Estimated tests:** 4 new (UT3 to UT6 in `tests/test_ad1356_s1_unknown_tools.py`), 0 removed, 2 functions changed (UT2; CC5 of `tests/test_ad1356_s3_chain_of_command.py`, 5 cases after R1).
**Size:** a production change of a few lines in one function, plus one docstring sentence; R1 (review round 1, D7) adds a few lines to `approval_payload` and one predicate; the rest is tests and trackers.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-15 (R1: review round 1, findings F1 to F3)

## 1. Problem

A model is shown an `mcp:{server}:{tool}` tool only under `llm_function_name(tool_id)`, a provider-safe alias (`src/probos/cognitive/swe_harness/tool_call.py:64-71`, BF-754), so the alias is the only name it can return. The executor maps the alias back to the registered id (`ToolExecutor._resolve_tool_id`, `src/probos/tools/executor.py:560-606`; used at `:634`). The agent-work confinement runs before that, in `_DispatchGuardMixin._invoke_reserved_body` (`src/probos/cognitive/agentic_dispatch.py:800`), on the name as sent:

- `:808` `tool_id = requested_tool_id`;
- `:845-849` (AD-1356 S1.1) resolves the name only to refuse an unregistered one; `tool_id` stays the alias;
- `:850-851` the set check and `confinement.refuse_or_admit(agent_id, tool_id, params)` get the alias;
- `:931-932` `confinement.record_admitted(agent_id, tool_id, admitted_params, result)` gets the alias.

The runner's gate files that id (`approval_payload`, `src/probos/agent_work_runner.py:722`; defined `:169`; the recorder calls it at `:137`). The approval service reads the tier from it (`filed_call_tier`, `src/probos/delegated_approvals.py:187`), and `src/probos/tools/effect_tiers.py:114-115` gives `tool_tier` (critical for an unlisted id) to any id that does not start with `mcp:`. So the filed call of an OPEN MCP tool is `CAPTAIN_RESERVED`, against DECISIONS.md:1911 ("OPEN elevated"). It fails closed: no call runs that should not. Reproduced on this base by the orchestrator: CC5 with only its script on the alias gives `[open]` FAILED with `Refusal.CAPTAIN_RESERVED` (`logs/b982/repro/run-on-main.out.txt`).

UT2 of `tests/test_ad1356_s1_unknown_tools.py` (`:97`, `assert asked == ["hull_survey", alias]`) asserts the defect: the alias at the gate.

## 2. Solution overview

Under a confinement, keep one id, `confined_id`, for the confinement's three uses: the set check, `refuse_or_admit` and `record_admitted`. It is the id S1.1's existing `_resolve_tool_id` call answers, when that answer is not None (after S1.1's refusal, a non-None answer is always registered). An ambiguous name (None), a call with no registry and a non-str name keep the name as sent. Then one call is filed, kept (BF-947's key) and approved under one id, whatever name the model used, and `filed_call_tier` reads the tool's own tier.

Rejected:
- Teaching `filed_call_tier` aliases. The filed id, the carried key and the admission key would still differ between an alias call and an id call.
- Passing the resolved id to the whole body, including the base call. That changes the name plan mode, the inbox and the base call are given, and fixes no defect (section 3, D2).
- Honouring requests filed under an alias in the runner's admissions. One approval would cover two strings, which changes BF-947's exact-key rule for a transitional case (D3).

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Resolve once, where S1.1 already resolves; `confined_id` feeds the set check, the gate and `record_admitted` | One call, one id, through filing, the carried key and the approval. No second resolution is added |
| D2 | Out of scope: `_plan_mode_tool_ids`, `_deferred_schemas.withhold_call`, `_park_or_admit`, the browser checks and the base call keep the name as sent; `denied_tools` and AD-856's log record the id the `ToolPermissionDenied` carries, unchanged (L3) | `PLAN_MODE_TOOL_IDS` (`agent_mode.py:68-83`) holds only provider-valid ids, so an alias and its id get the same answer. `withhold_call` already maps an id to its alias (`tool_manifest.py:325`). `_park_or_admit` acts only on `"browser"` (`agentic_dispatch.py:230`, `:1233`), which is provider-valid. The base call resolves the name itself (`executor.py:634`). Changing them changes the name plan mode, the inbox and the base call are given, and fixes no defect |
| D3 | Requests filed under an alias before this change: accepted as recorded limit L1, with no test | It fails closed. A pending alias request is decided as critical. Once fulfilled, the resumed call is filed again under the registered id and decided by its tier. A fulfilled alias request admits nothing, and a denied one still cancels the item (`agent_work_runner.py:273-302`). Nothing runs unapproved or twice. Such requests exist only where `mcp.agent_tools_enabled` (default False, `config.py:2797`) was on. Handling them would change BF-947's exact-key admission (a governance control). A test that asserts the second filing would make the limit the contract |
| D4 | Severity Medium; ordinary reach (not injected) when `mcp.agent_tools_enabled` is on; fail-closed over-restriction | Every MCP call from agent work is filed under its alias, because the model is shown only the alias. No call runs that should not. AD-1356 S3's delegation does nothing for MCP tools. It blocks #1796 |
| D5 | UT2's alias assertion changes in M1, with the fix | It asserted the defect. Moving it with the fix keeps every commit green, and the reason is recorded inline |
| D6 | The regression test is CC5 in place (alias script, plus the filed id checked in all three cases); the unit tests UT3 to UT5 are appended to the S1 file | CC5 crosses the seam through the real executor, gate, stores and service. UT3 catches the `record_admitted` mutant, which CC5 cannot: the item ends and its carried results are dropped. No new file, so #1796's census does not change |
| D7 | Review round 1 (F1): a registered id the action payload's tool-id pattern (`capability_request._TOOL_ID_RE`, `^[a-z0-9_:.-]{1,64}$`) refuses is filed under its provider alias, as on the base. `approval_payload` makes the swap through `is_action_tool_id`, the one predicate `validate_action_payload` also reads; the gate's rationale names the filed id. New cases: CC5 `[len65]` and `[slash]`, and UT6 | Without it, M1 regressed every MCP id longer than 64 characters, or holding a character the alias removes: the base filed such a call (critical, for the Captain) and M1 refused it unfiled (`CONFINED_CALL_NOT_FILED`). The runner owns the filing rule, so the swap is there, not in the confinement, which would otherwise have to know one gate's payload shape. The alias is a pure function of the id, so the gate's key, the admissions, the recorder's key and the rationale agree. The rationale never shows a remote string the pattern refuses. Rejected: widening the pattern for an exact `mcp:` id (a persisted and wire shape with a UI mirror and a security purpose; its own item, L6) |

## 4. Milestones and commits

- **M1** `src/probos/cognitive/agentic_dispatch.py` (P1-1 to P1-3) and UT2 of `tests/test_ad1356_s1_unknown_tools.py` (P1-4, P1-5).
  Subject: `Agent-work confinement files, keeps and approves a call under the registered id an alias maps to`
  Body: one paragraph from sections 1 and 2 (D1, D2, D5), then `Refs #1817.`
- **M2** `tests/test_ad1356_s3_chain_of_command.py` (P2-1 to P2-3) and `tests/test_ad1356_s1_unknown_tools.py` (P2-4, P2-5).
  Subject: `Chain-of-command MCP test calls the provider alias, and unit tests pin the confinement's registered id`
  Body: one paragraph from D6, then `Refs #1817.`
- **M3** trackers: P3-1, P3-2, then `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`.
  Subject: `Trackers for the confinement's registered tool id`
  Body: `Refs #1817.`
- **R1** (review round 1, D7): `src/probos/capability_request.py`, `src/probos/agent_work_runner.py`, the two test files, this contract, `PROGRESS.md` and `DECISIONS.md`, then the ledger pair regenerated as in M3.
  Subject: `Agent-work runner files a call whose registered id the payload pattern refuses under its alias`
  Body: one paragraph from D7, then `Refs #1817.`

No subject carries an `AD-` or `BF-` token, or a word GitHub reads as a closing keyword (`close`, `fix` or `resolve`, in any form; the orchestrator's message scans reject them). Never `git add -A`; stage the named files only.

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py` (M3), run `git diff --check` and `git diff --stat`, and commit per section 4.
- **May not:** run pytest (the orchestrator runs every test), edit any file not named here, change any other line of `_invoke_reserved_body`, add `skip`/`xfail`/retry, or reword a SEARCH anchor. If a SEARCH does not match exactly once at its turn, stop and report.

## 6. Behaviour table (after M1)

| Name the model sends | `_resolve_tool_id` | S1.1 | `confined_id` | Set check, gate, record |
|---|---|---|---|---|
| alias of a registered id | the registered id | passes | the registered id | the registered id |
| a registered provider-valid id | itself | passes | itself | itself (unchanged) |
| unregistered name | itself | refused, as before | -- | not reached |
| ambiguous (two claimants) | None | passes | the name as sent | the name as sent (unchanged) |
| any name, no registry | not called | not run | the name as sent | unchanged |
| non-str | not called | not run | the value as sent | unchanged (the runner refuses it) |

R1 (D7): when `confined_id` is a registered id the action payload's tool-id pattern refuses, the runner's gate and recorder file and keep the call under `llm_function_name(confined_id)`, as the base did, and only the Captain decides it. When the alias is refused too (an upper-case name), the call is refused unfiled, as on the base (L6).

## 7. The contract

### 7.1 `src/probos/cognitive/agentic_dispatch.py` and UT2 (M1)

**P1-1** (`src/probos/cognitive/agentic_dispatch.py`: `ToolCallConfinement` docstring)
SEARCH:
```
    reading the plan. BF-947: ``record``, when set, is handed results of admitted calls (``record_admitted``).
    """
```
REPLACE:
```
    reading the plan. BF-947: ``record``, when set, is handed results of admitted calls (``record_admitted``).
    BF-982: ``tool_ids``, ``gate`` and ``record`` see the registered id a provider alias resolves to; an ambiguous
    name, or any name when the executor has no registry, is passed as the model sent it.
    """
```

**P1-2** (`src/probos/cognitive/agentic_dispatch.py`: `_invoke_reserved_body`, the id the confinement sees)
SEARCH:
```
        admitted_params = params  # BF-947: what the gate was asked, for record_admitted
        # AD-1356 S1.1: under a confinement, when the executor has a registry, a str tool id that resolves to no
        # registered tool is refused here, before the confinement's set and gate, so it is never filed. An ambiguous
        # name (``_resolve_tool_id`` answers None) goes on to the gate.
        if confinement is not None and self._registry is not None and type(tool_id) is str:
            resolved = self._resolve_tool_id(tool_id)
            if resolved is not None and self._registry.get(resolved) is None:
                strict_log("confinement", "confinement_refused")
                return refuse(ToolResult(error=UNREGISTERED_TOOL_REFUSAL), "confinement_refused")
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
```
REPLACE:
```
        admitted_params = params  # BF-947: what the gate was asked, for record_admitted
        # BF-982: the id the confinement's set, gate and record see. A provider alias (the only name a model is shown
        # for an mcp: tool) becomes the registered id it resolves to, so one call is filed, kept and approved under one
        # id and filed_call_tier reads the tool's own tier. Plan mode, deferred schemas, the browser checks and the
        # executor below keep the name the model sent: each answers an alias and its id alike or resolves it itself.
        confined_id = tool_id
        # AD-1356 S1.1: under a confinement, when the executor has a registry, a str tool id that resolves to no
        # registered tool is refused here, before the confinement's set and gate, so it is never filed. An ambiguous
        # name (``_resolve_tool_id`` answers None) goes on to the gate.
        if confinement is not None and self._registry is not None and type(tool_id) is str:
            resolved = self._resolve_tool_id(tool_id)
            if resolved is not None and self._registry.get(resolved) is None:
                strict_log("confinement", "confinement_refused")
                return refuse(ToolResult(error=UNREGISTERED_TOOL_REFUSAL), "confinement_refused")
            if resolved is not None:
                confined_id = resolved
        if confinement is not None and confined_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, confined_id, params)
```

**P1-3** (`src/probos/cognitive/agentic_dispatch.py`: `_invoke_reserved_body`, the record of an admitted call)
SEARCH:
```
        if confined_admission and confinement is not None:
            confinement.record_admitted(agent_id, tool_id, admitted_params, result)
```
REPLACE:
```
        if confined_admission and confinement is not None:
            confinement.record_admitted(agent_id, confined_id, admitted_params, result)
```

**P1-4** (`tests/test_ad1356_s1_unknown_tools.py`: UT2 docstring)
SEARCH:
```
    asking the gate, and the refusal is a never-ran policy outcome; a registered tool outside the set, by its id or by
    its provider alias, is put to the gate."""
```
REPLACE:
```
    asking the gate, and the refusal is a never-ran policy outcome; a registered tool outside the set, by its id or by
    its provider alias, is put to the gate, under its registered id either way (BF-982)."""
```

**P1-5** (`tests/test_ad1356_s1_unknown_tools.py`: UT2, the gate's ids; this line asserted the defect)
SEARCH:
```
        assert (await executor.invoke("forge-1", tool_id, {})).error == CONFINED_CALL_FILED
    assert asked == ["hull_survey", alias]
```
REPLACE:
```
        assert (await executor.invoke("forge-1", tool_id, {})).error == CONFINED_CALL_FILED
    # BF-982 (#1817): the gate is asked under the registered id the alias resolves to. This line asserted the alias
    # itself, which pinned the defect: a call filed under the alias is classified critical whatever the tool's tier.
    assert asked == ["hull_survey", "ops:hull:survey"]
```

### 7.2 `tests/test_ad1356_s3_chain_of_command.py` (M2)

**P2-1** (`tests/test_ad1356_s3_chain_of_command.py`: import `llm_function_name`; it sorts after the `agentic_dispatch` import, away from P0-257's two lines)
SEARCH:
```
from probos.cognitive.agentic_dispatch import _McpTool
from probos.delegated_approvals import AUDIT_CATEGORY, DeciderRole, DelegatedApprovalService, Refusal, RequestClass
```
REPLACE:
```
from probos.cognitive.agentic_dispatch import _McpTool
from probos.cognitive.swe_harness.tool_call import llm_function_name
from probos.delegated_approvals import AUDIT_CATEGORY, DeciderRole, DelegatedApprovalService, Refusal, RequestClass
```

**P2-2** (`tests/test_ad1356_s3_chain_of_command.py`: CC5's script calls the alias, the only name a model is shown)
SEARCH:
```
    query = {"query": "drift budget"}
    script = [_call(tool.tool_id, query, "c1"), _final("Waiting."), _call(tool.tool_id, query, "c2"), _final(ANSWER)]
```
REPLACE:
```
    query = {"query": "drift budget"}
    # BF-982 (#1817): a model is shown an mcp: tool only under its provider alias, so the script calls the alias.
    alias = llm_function_name(tool.tool_id)
    script = [_call(alias, query, "c1"), _final("Waiting."), _call(alias, query, "c2"), _final(ANSWER)]
```

**P2-3** (`tests/test_ad1356_s3_chain_of_command.py`: CC5 checks the filed id in all three cases)
SEARCH:
```
            item_id = await _self_task(rig, "Look up the drift budget")
            request = await _parked_on(rig, item_id)
```
REPLACE:
```
            item_id = await _self_task(rig, "Look up the drift budget")
            request = await _parked_on(rig, item_id)
            assert request.payload["tool_id"] == tool.tool_id  # BF-982: filed under the registered id, not the alias
```

### 7.3 `tests/test_ad1356_s1_unknown_tools.py` (M2)

**P2-4** (`tests/test_ad1356_s1_unknown_tools.py`: import `CONFINEMENT_ADMIT`)
SEARCH:
```
    CONFINED_CALL_FILED,
    CONFINEMENT_FILED,
    UNREGISTERED_TOOL_REFUSAL,
```
REPLACE:
```
    CONFINED_CALL_FILED,
    CONFINEMENT_ADMIT,
    CONFINEMENT_FILED,
    UNREGISTERED_TOOL_REFUSAL,
```

**P2-5** (`tests/test_ad1356_s1_unknown_tools.py`: UT3 to UT5 after UT2; they call the executor directly, never the loop)
SEARCH:
```
    assert UNREGISTERED_TOOL_REFUSAL in agentic_dispatch._NEVER_RAN_REFUSALS
    assert classify_tool_fault_error(UNREGISTERED_TOOL_REFUSAL) == "permission_denied"
    assert not is_capability_gap(UNREGISTERED_TOOL_REFUSAL) and "search_capabilities" in UNREGISTERED_TOOL_REFUSAL
```
REPLACE:
```
    assert UNREGISTERED_TOOL_REFUSAL in agentic_dispatch._NEVER_RAN_REFUSALS
    assert classify_tool_fault_error(UNREGISTERED_TOOL_REFUSAL) == "permission_denied"
    assert not is_capability_gap(UNREGISTERED_TOOL_REFUSAL) and "search_capabilities" in UNREGISTERED_TOOL_REFUSAL


# BF-982 (#1817): a registered id the provider rejects, so a model is shown only its alias (llm_function_name).
CANONICAL = "ops:hull:survey"


def _confined(
    tool_ids: frozenset[str], verdict: str, *also: str,
) -> tuple[DispatchToolExecutor, list[Any], list[Any]]:
    """An executor over a registry holding ``CANONICAL`` and ``also``, confined to ``tool_ids``. The gate answers
    ``verdict`` and notes each id it is asked; ``record`` notes each id it is handed with the result's error."""
    registry = ToolRegistry()
    for tool_id in (CANONICAL, *also):
        registry.register(_Probe(tool_id))
    executor = DispatchToolExecutor(registry=registry)
    asked: list[Any] = []
    recorded: list[Any] = []

    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        asked.append(tool_id)
        return verdict

    def record(agent_id: str, tool_id: Any, params: Any, result: ToolResult) -> None:
        recorded.append((tool_id, result.error))

    executor.confine_calls(ToolCallConfinement(tool_ids, gate, record=record))
    return executor, asked, recorded


# UT3
async def test_an_alias_call_is_gated_and_recorded_under_the_registered_id() -> None:
    """BF-982: by its alias or by its id, an admitted call reaches the gate and ``record_admitted`` under the registered
    id, so the runner files it, keeps its result (BF-947's key) and admits its approval under one id."""
    executor, asked, recorded = _confined(frozenset({"event_log_query"}), CONFINEMENT_ADMIT)
    for name in (llm_function_name(CANONICAL), CANONICAL):
        assert (await executor.invoke("forge-1", name, {})).error is None
    assert asked == [CANONICAL, CANONICAL]
    assert recorded == [(CANONICAL, None), (CANONICAL, None)]


# UT4
async def test_an_alias_of_a_tool_in_the_direct_set_runs_without_the_gate() -> None:
    """BF-982: the direct-set check reads the registered id too, so the alias runs directly; nothing is asked or
    recorded."""
    executor, asked, recorded = _confined(frozenset({CANONICAL}), CONFINEMENT_FILED)
    result = await executor.invoke("forge-1", llm_function_name(CANONICAL), {})
    assert result.error is None
    assert asked == [] and recorded == []


# UT5
async def test_an_ambiguous_name_goes_to_the_gate_as_the_model_sent_it() -> None:
    """BF-982 keeps AD-1356 S1.1's rule for a name two registered tools would be offered under (``_resolve_tool_id``
    answers None): it is put to the gate as sent, and filing it runs nothing."""
    alias = llm_function_name(CANONICAL)
    executor, asked, recorded = _confined(frozenset({"event_log_query"}), CONFINEMENT_FILED, alias)
    assert (await executor.invoke("forge-1", alias, {})).error == CONFINED_CALL_FILED
    assert asked == [alias] and recorded == []
```

### 7.4 No overlap with #1796's pending pairs (v1p3c), line by line on `799869715f`

`tests/test_ad1356_s3_chain_of_command.py`:
- P2-1 replaces `:26-:27` and inserts one line between them. P0-257's SEARCH is `:30-:31` (the `effect_tiers` and `test_ad1347_s1_agent_work` imports). `:28-:29` lie between, unchanged. After P2-1, P0-257's two lines are `:31-:32`, the same text, once.
- P2-2 replaces `:242-:243` (`:242` kept, `:243` becomes three lines). P0-259's SEARCH is `:245-:248` (`rig.tools.register(` ... `async with _chain(rig) as (service, _audit, _told):`). `:244` (`async with _rig(...)`) lies between, unchanged. P0-259's lines and its `tool.tool_id` tag stay as they are.
- P2-3 replaces `:249-:250` and inserts one line after `:250`. P0-259's last line is `:248`. P0-259's REPLACE inserts between `:247` and `:248`, which leaves `:248-:250` contiguous, so the two pairs apply in either order.
- P0-258 (`:165-:166`, CC2) is untouched.

`tests/test_ad1356_s1_unknown_tools.py`:
- #1796's pairs here are P2-34 (`:53`) and P2-35 (`:69-:70`), both in UT1. This slice touches `:16-:18` (P2-4), `:77-:78` (P1-4), `:96-:97` (P1-5) and `:98-:100` (P2-5). None of these overlap.

`src/probos/cognitive/agentic_dispatch.py`:
- #1796's pairs are P2-13 (the `agentic_loop` import), P2-14 (`_NEVER_RAN_REFUSALS`, `:332-:335`), P2-15 (fault classification), P2-16 (the plan-mode comment near `:3601`) and P2-17 (`_loop_kwargs`). This slice touches `:346-:347` and `:841-:851` and `:931-:932`. None of these overlap.

### 7.5 Trackers (M3)

**P3-1** (`PROGRESS.md`: BF-982 entry at the top)
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-982 (2026-11-15), #1817 -- an agent-work call to an MCP tool is filed, kept and approved under the tool's registered id, not the provider alias the model was shown, so a department chief decides an OPEN tool's call as AD-1356 S3 decided.** Under a confinement, `_invoke_reserved_body` passed the name as the model sent it to the confinement's set check, gate and `record_admitted`. A model is shown an `mcp:` tool only under its `llm_function_name` alias, so every such call was filed under the alias, and `filed_call_tier`, which reads an MCP tool only from an `mcp:` id, made it critical: the Captain decided every one. It failed closed. The three uses now take the id AD-1356 S1.1's resolution already answers; an ambiguous name or a call with no registry keeps the name sent. CC5 of `tests/test_ad1356_s3_chain_of_command.py` now scripts the alias and checks the filed id; UT2 of `tests/test_ad1356_s1_unknown_tools.py`, which asserted the alias at the gate, now asserts the registered id; UT3 to UT5 pin the gate, the record, the direct set and the ambiguous case. A request filed under an alias before this change is not matched by the resumed call, which is filed again (recorded limit; nothing runs unapproved or twice). Reached only with `mcp.agent_tools_enabled` on (default off). Prerequisite of #1796. The decisions are in DECISIONS.md (BF-982); the contract is `prompts/bf-982-mcp-alias-filing.md`.
```

**P3-2** (`DECISIONS.md`: BF-982 entry after AD-1356 S3 and S4)
SEARCH:
```markdown
### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```
REPLACE:
```markdown
### BF-982 -- An agent-work call to an MCP tool is filed and decided under its registered id, not the provider alias (2026-11-15, #1817)

- *Scope.* `cognitive/agentic_dispatch.py` (`_DispatchGuardMixin._invoke_reserved_body`: the confinement's set check, gate and `record_admitted` take the id S1.1's resolution answers; the `ToolCallConfinement` docstring); `tests/test_ad1356_s3_chain_of_command.py` (CC5 calls the alias and checks the filed id); `tests/test_ad1356_s1_unknown_tools.py` (UT2, which asserted the alias at the gate, updated; UT3 to UT5 added). Contract `prompts/bf-982-mcp-alias-filing.md`.
- *Cause.* A model is shown an `mcp:` tool only under its `llm_function_name` alias (BF-754). The confinement gave its gate the name as sent, so the call was filed under the alias, and `filed_call_tier` reads only an `mcp:` id as an MCP tool: every such call was critical and Captain-reserved, against AD-1356 S3 (OPEN is elevated). It failed closed.
- *D1.* Resolve once, where S1.1 already resolves; the three confinement uses read one id. An ambiguous name, a call with no registry and a non-str name keep the name sent.
- *D2.* Plan mode, deferred schemas, the AD-1154 inbox, the browser checks and the executor call keep the name sent: each answers an alias and its id alike or resolves the name itself. `denied_tools` and AD-856's records keep the name the model used.
- *D3 (recorded limit).* A request filed under an alias before this change is not matched by the resumed call's key. A pending one is decided as critical; once fulfilled, the call is filed again under its id and decided by its tier; a denied one still ends the item. Nothing runs unapproved or twice. It exists only where `mcp.agent_tools_enabled` (default off) was on; live state was not checked.
- *Rejected.* Teaching `filed_call_tier` aliases (the filed id and BF-947's key would still differ between names); honouring alias requests in the runner's admissions (one approval covering two strings, a change to BF-947's exact key, for a transitional case); passing the resolved id to the whole body (changes `denied_tools` and AD-856's records for no defect).
- *Reversal.* Revert the BF-982 commits. A request filed under a registered id stays valid; its resumed call is then filed again under the alias, as critical.

### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```

The orchestrator appends a `*Mutation campaign of record.*` bullet to this entry after section 8.3.

Then run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` and stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`.

### 7.6 R1 (review round 1, D7), on `c3d90e0f`

The pairs are in commit R1: `is_action_tool_id` (capability_request), which `validate_action_payload` now reads; `approval_payload` swapping a refused id for its alias; the gate's rationale naming the filed id; CC5 `[len65]` and `[slash]` with their premise and a filed-id and rationale assertion on every case; UT6. #1796 (v1p3d) has no pair on `agent_work_runner.py` or `capability_request.py`. R1's CC5 pairs leave P0-259's four lines unchanged, and R1's import pairs leave P0-257's two lines unchanged. The S1 file's import pair and UT6 do not touch P2-34 or P2-35. The new CC5 cases inherit P0-259's offer (`OfferedMcpTools(tool.tool_id)`; `MCPDispatchOffer._valid_tool_id` admits any `mcp:{server}:{tool}`), so #1796 needs no new pair. Its expected counts move: S1 +1, S3 +2, and the `-k "mcp or ad1019"` set +2.

## 8. Gates (the orchestrator runs all of them; the Builder runs none)

### 8.1 Base counts, before the build (orchestrator, on `799869715f`)

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s3_chain_of_command.py tests/test_ad1347_s3_execution.py tests/test_ad1356_s1_unknown_tools.py tests/test_ad1356_s1_recovery_reads.py tests/test_ad1356_s1_input_errors.py tests/test_ad1356_s2_tool_effect_table.py tests/test_ad1356_s4_who_decides.py tests/test_bf947_confinement_answer.py tests/test_bf947_multi_call_agent_work.py tests/test_ad1213_delegated_approvals.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests -k "mcp or ad1019" -n 0 -p no:randomly -q
```

Record each file's count. `tests/test_ad1356_s1_unknown_tools.py` holds 2 cases on the base.

### 8.2 Focused check on the built tree

The same two commands. Expected:
- `tests/test_ad1356_s1_unknown_tools.py`: 6 passed (base 2, plus UT3 to UT6).
- `tests/test_ad1356_s3_chain_of_command.py`: its base count plus 2 (CC5 `[len65]` and `[slash]`, R1), all passed.
- Every other file: its base count, all passed. CC5's five cases pass.
- The `-k "mcp or ad1019"` set: the base count plus 2 (CC5's two R1 cases), 0 failed. No other new test name or module matches `mcp` or `ad1019`.
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`: passes.

Then CC5 three times serially: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s3_chain_of_command.py -k an_mcp_call -n 0 -p no:randomly -q`. Expected each time: 5 passed.

### 8.3 Mutation campaign (one row at a time, restored before the next; win32)

Selector for every row: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s1_unknown_tools.py tests/test_ad1356_s3_chain_of_command.py -n 0 -p no:randomly -q`. The unmutated baseline is 8.2's count for these two files. This is the campaign of record: record the tree id and the sha256 of `src/probos/cognitive/agentic_dispatch.py`, `src/probos/agent_work_runner.py`, `src/probos/capability_request.py` (R1), `tests/test_ad1356_s1_unknown_tools.py` and `tests/test_ad1356_s3_chain_of_command.py`. A rerun on files with the same hashes repeats nothing; a row whose file differs is rerun.

| Row | Original (whole stripped line, after M1) | Mutant | Expected killers |
|---|---|---|---|
| MU1 (record resolved, gate not) | `refusal = await confinement.refuse_or_admit(agent_id, confined_id, params)` | `refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)` | UT2 `assert asked == ["hull_survey", "ops:hull:survey"]`; UT3 `assert asked == [CANONICAL, CANONICAL]`; CC5 x3 `assert request.payload["tool_id"] == tool.tool_id` |
| MU2 (gate resolved, record not) | `confinement.record_admitted(agent_id, confined_id, admitted_params, result)` | `confinement.record_admitted(agent_id, tool_id, admitted_params, result)` | UT3 `assert recorded == [(CANONICAL, None), (CANONICAL, None)]` (CC5 cannot catch it: the item ends and its carried results are dropped) |
| MU3 (direct set on the alias) | `if confinement is not None and confined_id not in confinement.tool_ids:` | `if confinement is not None and tool_id not in confinement.tool_ids:` | UT4 `assert result.error is None` (the gate files it: `CONFINED_CALL_FILED`) |
| MU4 (never resolves) | `confined_id = resolved` | `pass` | UT2, UT3, UT4, CC5 x3 (`[open]` also at `outcome.refusal`) |
| MU5 (resolves an ambiguous name) | `if resolved is not None:` (the new one; the S1.1 line reads `if resolved is not None and self._registry.get(resolved) is None:`) | `if True:` | UT5 `assert asked == [alias] and recorded == []` (asked is `[None]`) |
| R0 (base product file, R1 tests) | `src/probos/cognitive/agentic_dispatch.py` restored from `799869715f` | -- | 6 fail: UT2, UT3, UT4, CC5 `[open]`, `[confirm]`, `[reaped]` (each at the filed-id assertion); UT5, UT6, CC5 `[len65]` and `[slash]` pass (the base gate sees the alias, which the pattern accepts) |
| MU6 (never swaps; `agent_work_runner.py`) | `if not is_action_tool_id(tool_id):` | `if False:` | UT6 `assert payload is not None and payload["tool_id"] == alias`; CC5 `[len65]`, `[slash]` at `_parked_on` (nothing is filed) |
| MU7 (always swaps; `agent_work_runner.py`) | `if not is_action_tool_id(tool_id):` | `if True:` | UT6 `assert approval_payload(CANONICAL, params, "wi-1")["tool_id"] == CANONICAL`; CC5 `[open]`, `[confirm]`, `[reaped]` at the filed-id and rationale assertion |
| MU8 (rationale names the sent id; `agent_work_runner.py`) | `rationale=f"agent work {work_item_id[:8]} called {payload['tool_id']}, a call that needs approval",` | `rationale=f"agent work {work_item_id[:8]} called {tool_id}, a call that needs approval",` | CC5 `[len65]`, `[slash]` at the filed-id and rationale assertion |
| MU9 (predicate ignores the pattern; `capability_request.py`) | `return type(tool_id) is str and _TOOL_ID_RE.fullmatch(tool_id) is not None` | `return type(tool_id) is str` | UT6 premise; CC5 `[len65]`, `[slash]` premise |
| R1r (M3's runner, R1's other files) | `src/probos/agent_work_runner.py` restored from `c3d90e0f` | -- | 3 fail: UT6, CC5 `[len65]`, `[slash]` (the round-1 regression) |

Record each row as KILLED (by the named assertion, or name the one that fired), SURVIVED or INVALID. Any survivor stops the slice for Architect triage.

### 8.4 Broad gate

Once for the wave, on its final committed head (#1796's contract, section 3, label `wave-1817-1796`). If #1796 is rescoped, split or parked, run it alone on this slice's committed M3 head with `--label mcp-alias-filing`.

## 9. Diff Reviewer: properties to verify

1. The diff touches only `src/probos/cognitive/agentic_dispatch.py`, `src/probos/agent_work_runner.py` and `src/probos/capability_request.py` (R1), the two test files, this contract (R1), `PROGRESS.md`, `DECISIONS.md` and the two regenerated ledger files.
2. In `_invoke_reserved_body`, one name, `confined_id`, reaches all three confinement uses (the set check, `refuse_or_admit`, `record_admitted`). It differs from the name sent only when `_resolve_tool_id` answered a non-None id, and S1.1's refusal of an unregistered id still runs first, unchanged.
3. No other use of the name changes: plan mode, `withhold_call`, the browser checks, `_park_or_admit` and the base call still receive `tool_id`. `denied_tools` and the AD-856 log record `getattr(exc, "tool_id", tool_id)`, the id the `ToolPermissionDenied` carries (the registered id when the registry or `_McpTool` refuses), as on the base.
4. Every fail-closed path answers as before: a non-str name, a call with no registry, an unregistered name (UT1 and UT2's first half) and an ambiguous name (UT5).
5. Each consumer of the confinement's id receives the registered id for an alias call, and they agree with one another. The consumers are: the runner's gate (`agent_work_runner.py:716-743`: `_recovery_read`, `approval_payload`, `action_dedup_key`, the carried lookup, the admissions, `file_action_request` and its rationale); the recorder (`:136-152`); `filed_call_tier` (`delegated_approvals.py:187`, `effect_tiers.py:114-126`); and the carried line of `task_text` (`:218`). BF-947's admission key and carried key are computed on the same id the gate filed.
6. The tests cross the seam: CC5 runs the alias through the real executor, gate, stores and AD-1213 service; `[open]` is decided by the chief, its bridge is asked once, and all three cases check the filed id. No assertion was weakened, and no `skip`, `xfail` or retry was added. UT2's changed line states inline why.
7. The pairs of #1796's contract (P0-257 to P0-259, P2-34, P2-35, P2-13 to P2-17) still match exactly once on the built tree (section 7.4).
8. Comments cite no line numbers; the files are ASCII with LF line endings; every SEARCH matched exactly once at its turn; the tracker entries describe the diff.
9. R1: `validate_action_payload` accepts exactly what it accepted (its tool-id check is `is_action_tool_id`, the same pattern), so the UI mirror (`ui/src/store/capabilityApprovals.ts`) and its fixture rows need no change. `approval_payload` returns a payload under the id when the pattern accepts it; under `llm_function_name(id)` when it refuses the id and accepts the alias; and None otherwise. No payload or rationale ever holds an id the pattern refuses. The gate's payload, key, carried lookup, admissions, filing and rationale, and the recorder's key, read one `payload["tool_id"]`, so a resumed call is admitted by the request it was filed under (CC5 `[len65]` and `[slash]` finish with one request).
10. R1: a call filed under the alias is critical (`filed_call_tier` of a non-`mcp:` id gives `tool_tier`'s answer for an unlisted id), so only the Captain decides it, as on the base; no call runs unapproved.

## 10. Verified Against Codebase (2026-11-15, `799869715f`, tree `33f1b1b79ce8`)

```
src/probos/cognitive/agentic_dispatch.py
  230: _APPROVAL_INBOX_TOOL_IDS: frozenset[str] = frozenset({"browser"})
  325-328: CONFINEMENT_ADMIT / _FILED / _REFUSED / _ANSWERED
  339-351: class ToolCallConfinement (tool_ids, gate, record); 346: "reading the plan. BF-947: ..." (1 occurrence)
  363-377: refuse_or_admit; 379-389: record_admitted
  800-808: _DispatchGuardMixin._invoke_reserved_body; tool_id = requested_tool_id
  839-841: confinement = self._confinement / confined_admission / admitted_params (841, 1 occurrence)
  845-849: S1.1 resolve and refuse; 850-851: set check and refuse_or_admit(agent_id, tool_id, params) (851, 1 occurrence)
  859: plan-mode check; 871: withhold_call(tool_id); 877-887: browser checks; 893-901: _park_or_admit
  908-910: super()._invoke_reserved_body(agent_id, tool_id, ...); 912-913: denied_tools
  931-932: record_admitted(agent_id, tool_id, admitted_params, result) (932, 1 occurrence)
  1000-1002: restrict_to_plan_mode; 1004-1007: confine_calls
  1233: if arming is None or tool_id not in _APPROVAL_INBOX_TOOL_IDS: return None
  1526-1539: DispatchToolExecutor.invoke -> _invoke_reserved_body unless protected effects
src/probos/tools/executor.py
  286-297: _catalog_claimants -> llm_function_name_claimants(tool_id, catalog.list_ids())
  560-606: _resolve_tool_id (canonical; the name unchanged when nothing claims it; None when ambiguous)
  634: resolved = self._resolve_tool_id(tool_id) (in _invoke_once); 795-797: base _invoke_reserved_body -> _invoke_once
src/probos/cognitive/swe_harness/tool_call.py
  64-71: llm_function_name; 74-84: llm_function_name_claimants (t == name or llm_function_name(t) == name)
src/probos/cognitive/tool_manifest.py
  317-333: withhold_call; 325: candidate = name if name in self._withheld else llm_function_name(name)
src/probos/cognitive/agent_mode.py
  68-83: PLAN_MODE_TOOL_IDS, 14 provider-valid ids
src/probos/tools/effect_tiers.py
  86-94: direct_tool_ids over ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS
  105-126: filed_call_tier; 114-115: non-"mcp:" id -> tool_tier(...)
src/probos/agent_work_runner.py
  133-154: CarriedResults.recorder (approval_payload at 137, action_dedup_key at 146)
  169-177: approval_payload; 210-218: task_text (carried line 218)
  265-281: _linked_calls, _admissions (fulfilled requests keyed by action_dedup_key of their payload)
  284-302: _cancel_or_park (denied -> cancelled; pending/approved -> park; fulfilled ignored)
  615-622: ToolCallConfinement(direct_tool_ids(...), self._gate_for(...), record=self.carried.recorder(item.id))
  716-743: gate (722 approval_payload, 725 key, 726-727 ANSWERED, 728-732 admissions, 735-738 file_action_request)
src/probos/delegated_approvals.py:187: filed_call_tier(call["tool_id"], tool_registry=...)
src/probos/capability_request.py:157-169: agent_work_call reads req.payload
src/probos/tools/registry.py:318-326: an empty default_permissions matrix gives READ to every rank
src/probos/config.py:2797: agent_tools_enabled: bool = False
tests/test_ad1356_s3_chain_of_command.py
  26-27: _McpTool import / delegated_approvals import; 30-31: P0-257's two imports
  102-107: _parked_on returns the one request; 165-166: P0-258's lines
  229-264: CC5; 242: query = {"query": "drift budget"} (1 occurrence); 243: script on tool.tool_id
  245-248: P0-259's lines; 249-250: _self_task "Look up the drift budget" / _parked_on (1 occurrence)
tests/test_ad1356_s1_unknown_tools.py
  16-23: agentic_dispatch import block; 25: llm_function_name import; 27: ToolResult; 28: ToolRegistry
  35-48: _Probe (output "probed"); 74-100: UT2; 77-78: docstring tail; 94: alias = ...; 96-97: the alias assertion
tests/test_ad1347_s3_execution.py:391: first.payload["tool_id"] (the payload-read pattern)
tests/test_ad1189_deferred_tool_schemas.py:1975-1986: a bare ToolRegistry + DispatchToolExecutor runs a registered tool
DECISIONS.md:1908 (AD-1356 S3 and S4), 1911 ("OPEN elevated"), 1919 (BF-947 heading, 1 occurrence)
PROGRESS.md:1 "# ProbOS Progress" (1 occurrence)
```

**Expected `git diff --stat`:**

```
 DECISIONS.md                              | ~10 +
 PROGRESS.md                               |  ~2 +
 docs/development/ad-ledger-snapshot.json  |  regenerated
 docs/development/open-ads-report.md       |  regenerated
 src/probos/cognitive/agentic_dispatch.py  | ~13 +-  (about +11 -2)
 tests/test_ad1356_s1_unknown_tools.py     | ~60 +-
 tests/test_ad1356_s3_chain_of_command.py  |  ~5 +-
```

## Absence Verified (2026-11-15)

```
CLAIM: only UT2 asserts the id the gate receives for an alias call
RUN:   Grep "ToolCallConfinement|confinement=" in tests/ ; Grep "llm_function_name\(" in tests/
FOUND: ToolCallConfinement in test_bf947_confinement_answer.py, test_ad1356_s1_unknown_tools.py, test_ad1347_s3_execution.py;
       llm_function_name( in 9 files, of which only test_ad1356_s1_unknown_tools.py also confines
HOLDS: yes (bf947 and ad1347_s3 use provider-valid ids only)

CLAIM: no source-scan test pins the changed lines
RUN:   Grep "refuse_or_admit\(agent_id|record_admitted\(agent_id|tool_id not in confinement|confined_id" in tests/
FOUND: none; _invoke_reserved_body appears in tests only as an override (test_ad1316_real_effect_routes.py:142)
HOLDS: yes

CLAIM: no #1796 (v1p3c) pair anchors on a line this slice edits
RUN:   grep "import _McpTool|drift budget|is put to the gate|asked == [\"hull_survey\", alias]" logs/b982/contract-b2.v1p3c.lf.md;
       grep label lines of pairs on src/ and on agentic_dispatch.py
FOUND: no anchor hits; agentic_dispatch pairs are P2-13 to P2-17 (import, _NEVER_RAN_REFUSALS, fault classification,
       plan-mode comment, _loop_kwargs)
HOLDS: yes (section 7.4)

CLAIM: the direct set and the plan-mode set hold no id a provider rejects
RUN:   Grep for a quoted non-[A-Za-z0-9_-] id in src/probos/tools/effect_tiers.py; Read agent_mode.py:68-83
FOUND: only the "mcp:" prefix literal (:114); 14 provider-valid plan-mode ids
HOLDS: yes (UT4 pins consistency, not a case reachable today)
```

R1 verified against `c3d90e0f` (2026-11-15):
- `src/probos/capability_request.py`: 79 `_TOOL_ID_RE = re.compile(r"^[a-z0-9_:.-]{1,64}$")`; 89 `THREAD_ID_MAX_CHARS: int = _THREAD_ID_MAX`; 216 the tool-id check (1 occurrence); 486-491 `action_dedup_key(*, agent_id, payload, work_item_id)`.
- `src/probos/agent_work_runner.py`: 55-62 the `capability_request` import block; 133-154 the recorder (`approval_payload` at 137); 140 the lazy-import pattern; 169-177 `approval_payload`; 722 the gate's `approval_payload`; 735-738 `file_action_request` with `called {tool_id}` (1 occurrence).
- `src/probos/cognitive/swe_harness/tool_call.py:59-71`: the alias keeps case, keeps only `[A-Za-z0-9_-]`, is at most 64 characters, and ends in a 16-hex digest.
- `src/probos/cognitive/mcp_workbench.py`: 751 `tool_id = f"mcp:{server_name}:{tool_name}"` (no sanitising); 215-224 `_valid_tool_id` admits any `mcp:{server}:{tool}`.
- `src/probos/cognitive/agentic_dispatch.py:920-931`: `denied = getattr(exc, "tool_id", tool_id)`, appended to `denied_tools` and logged by AD-856; `src/probos/tools/registry.py:70` `self.tool_id = tool_id`.
- `tests/test_ad1356_s3_chain_of_command.py:136` (CC1's rationale, `list_files`, unchanged by R1).

R1 absence (2026-11-15):
- CLAIM: `approval_payload` has no caller in src beyond the gate and the recorder. RUN: Grep `approval_payload\(` in `*.py`. FOUND: `agent_work_runner.py:137, 169 (def), 722`; tests `test_ad1347_s3_execution.py`, `test_ad1356_replay_approval_tiers.py:72`, `test_bf947_multi_call_agent_work.py`, each with ids that file today, so the pattern accepts them and R1 does not alter them. HOLDS: yes.
- CLAIM: no #1796 (v1p3d) pair touches `agent_work_runner.py`, `capability_request.py` or the CC5 lines R1 edits. RUN: Grep `agent_work_runner|approval_payload|capability_request` and `drift budget|bridge\.asked|_parked_on|Look up the|is_action_tool_id` in `logs/b982r1/contract-b2.v1p3d.lf.md`. FOUND: no pair or anchor on either. HOLDS: yes.
- CLAIM: no test pins the rationale or validator line R1 changes. RUN: Grep `a call that needs approval|called \{tool_id\}` in `*.py`; Grep `_TOOL_ID_RE` in the repo. FOUND: CC1 at `:136` only (`list_files`); `_TOOL_ID_RE` only at `capability_request.py:79, 216` and a comment at `continue_or_ask.py:100`. HOLDS: yes.

## 11. What this does NOT change, and recorded limits

Out of scope:
- `filed_call_tier`, `tool_tier` and the tier tables;
- the runner's gate, recorder and admissions, except R1's filing id and rationale (D7);
- the action payload's tool-id pattern, `validate_action_payload`'s accepted set and its UI mirror (L6);
- plan mode, AD-1189, AD-1154, the browser checks, the base call, `denied_tools`;
- the loop (#1796);
- `_resolve_tool_id` itself.

Recorded limits:
- **L1.** A request filed under an alias before this change is not matched by the resumed call (D3). It costs one extra decision, and nothing runs unapproved or twice. Live state was not checked.
- **L2.** The gate and the base call each resolve the name (`_invoke_reserved_body`, then `_invoke_once`). A registry change during the gate's await can make the base call answer "ambiguous" or "not found" for a call the gate admitted. It can also run a different tool. If the registered tool is replaced by one whose own id is the alias string, `llm_function_name_claimants` counts it (`t == name`), and the base call runs it while the gate and the recorder saw the registered id. Pre-existing (the base does the same) and injected-only: an `mcp:` id holds a colon and an alias never does, so only code that registers an alias-shaped id during the await reaches it. Follow-up (the wave's one): pin the admitted id through execution, or refuse a call whose resolution changed.
- **L3.** `denied_tools` and AD-856's log record the id the `ToolPermissionDenied` carries (`getattr(exc, "tool_id", tool_id)`): the registered id when the registry or `_McpTool` refuses, and the name sent only when the exception carries none. Unchanged by this slice.
- **L4.** The carried-results line of `task_text` now names the id the call was filed under (the registered id, or the alias for one the payload pattern refuses, R1), as its "Tool named:" line already does. A repeat under either name gets the same key and is answered.
- **L5.** Not run here: the Architect ran no test, of M1 to M3 or of R1. If UT3 or UT4 returns an error from the executor for a reason other than the confinement, or CC5 `[len65]` or `[slash]` fails anywhere but a premise, filed-id or tier assertion, stop and report.
- **L6.** R1 restores the base for a registered id the action payload's tool-id pattern (`^[a-z0-9_:.-]{1,64}$`) refuses: the call is filed under its alias, and the Captain decides it whatever its AD-1019b risk. When the alias is refused too, because the name holds an upper-case letter, the call is refused unfiled and the item ends (`CONFINED_CALL_NOT_FILED`), on the base as here. MCP tool names are case-sensitive and may run to 128 characters (SEP-986, the 2025-11-25 spec), so both are reachable whenever `mcp.agent_tools_enabled` is on. They are pre-existing and their own item, an independently reachable defect outside the wave's one follow-up: file an exact `mcp:` id under a pattern that admits its spec-valid names, moving `validate_action_payload`, the UI mirror (`ui/src/store/capabilityApprovals.ts`) and the shared fixture rows together. No test pins either limit.

## 12. Prior art and blind spots

This is a ProbOS plumbing fix with no outside analogue, so no external search was made.
- **Internal, absorbed:** BF-754 and BF-757 (the alias and the refusal of ambiguous names, `executor.py:560-606`); AD-1356 S1.1 (the existing resolution point); BF-947 (the exact-key admission, kept exact).
- **Blind spots found:** UT2 asserted the defect (moved in M1). CC5 cannot catch a `record_admitted` mutant, because carried results are dropped when the item ends, so UT3 does. Requests filed before the change (L1). The double resolution (L2).
- **Found by review round 1:** the filing pattern refuses ids the alias had sanitised (F1; D7, L6); the second resolution can run a substituted tool (F2, L2); a denial's id comes from the exception (F3, L3). External, for L6 only: MCP tool names are case-sensitive and run to 128 characters (https://modelcontextprotocol.io/seps/986-specify-format-for-tool-names); absorbed as a limit, and the pattern change is deferred to its own item.

## 13. Acceptance criteria

1. Section 8.2's counts on the built tree, and CC5 5 of 5 passed three times serially.
2. MU1 to MU9 are killed, each by the named assertion (or the one that fired is recorded); R0 shows its 6 failures and R1r its 3, all on one recorded tree.
3. The diff is exactly the expected `--stat` files.
4. One canonical broad gate with a receipt.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
