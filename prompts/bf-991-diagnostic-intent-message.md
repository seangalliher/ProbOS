# BF-991 (#1840): `/diagnostic` reaches the Diagnostician at the level it asks for, and the handler prints the diagnosis the LLM returns

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20 (amendment A1, section 17)

**Verified by:** the orchestrator, 2026-11-20: every pair and every check of section 15 was run on an oracle tree before the Builder started (section 16). One count of section 6 is corrected there: after D1-D2 the new file has 7 green and 7 red.

**Status:** build-ready: the oracle checks of section 15 passed (section 16). Issue #1840; the PR says `Refs #1840`. One BF number, BF-991, taken in the issue title. AV3 shows no collision. The number appears only in REPLACE text, new-file text, new-file paths and tracker text, never in a SEARCH, except where a SEARCH quotes BF-990's tracker text, which already names it, and A1-3's SEARCH (section 17), which quotes the comment that M1 added. Amended by A1 after review round 1 (section 17).

**Base:** `e8e660b8` (`e8e660b8562a8e529ab31762226c9e602dae9444`), the merge commit of PR #1841 (BF-988 and BF-990; merged 2026-11-20 11:12:59Z). Its tree, `3298a74c`, is the tree of `3331b4ac`, the head of #1841, which this contract was written against and whose oracle run is section 16. `git diff --stat cc601a72 3331b4ac` lists 13 files and none of the three source files edited here (`diagnostician.py`, `commands_diagnostic.py`, `panels.py`), nor `cognitive_agent.py`, `json_extract.py` or the three existing test files of the gate. Build on `origin/main`; if it has moved past this commit, run `audit\oracle_apply_b991.py --dry` against the new tree first.

**Line endings:** the working copies are CRLF (`git ls-files --eol`: `i/lf w/crlf` for all five edited files), and the SEARCH blocks below are LF. Match and write each file with its own line endings. Write the new test file with LF.

**Milestones:**
- **M1** (tier MEDIUM: a Captain-run command's behaviour, no shared contract):
  1. Write the new test file (7.1) alone, run it, and record the red base column (section 6).
  2. Apply D1 and D2 (`diagnostician.py`) only, and run the **premise gate**: test 8 must fail with output containing `Diagnostic error: 'str' object has no attribute 'get'`, and tests 1 to 7 must pass. If test 8 passes instead, stop and report; C1 to C4 are then dropped.
  3. Apply C1 to C4 (`commands_diagnostic.py`) and P1 (`panels.py`). Run the focused gate: green.
- **M2:** the trackers (7.5 to 7.8) and the generated ledger pair (7.9).
- **M3** (A1, tier LOW): section 17.

Each milestone is one Builder delegation and one local commit, in order. **The Builder does not commit**; the orchestrator commits by plumbing. No commit subject in the PR carries an `AD-` or `BF-` token. Suggested subjects:
- M1: `Read the diagnostic level from the message params and print the parsed diagnosis`
- M2: `Record the diagnostic repair in the status and decisions entries`
- M3: `Print the diagnostic reply and errors as received, without emoji codes or highlighting`

After M3, run one broad gate: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-991-1840 --receipt logs/gates/bf-991-1840.receipt.json`.

**Captain:** no Captain condition applies. This repairs a Captain-run command that is always registered (`shell.py:120`, `:336`). The spend is what AD-700/700c designed: at most one LLM call per invocation (L1 `deep`, L2 and L3 `fast`, none at L4 and L5). There is no new spend path, background trigger, schema, control or boundary.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| The override reads the level from the argument: `level = parse_level(intent.get("level"))` | `src/probos/agents/medical/diagnostician.py:83` (signature `:66` `intent: dict[str, Any]`; `super().perceive` at `:80`; the guard at `:82`) |
| The command sends an `IntentMessage` with the level under `params` | `src/probos/experience/commands/commands_diagnostic.py:65-70` |
| The lifecycle passes the message to `perceive` unchanged | `src/probos/cognitive/cognitive_agent.py:7609` |
| The base `perceive` accepts both shapes. For an `IntentMessage` it keeps `params` (the same object). Its dict branch keeps only `intent`, `params`, `context` and `correlation_id`, plus `id`/`thread_id` when given | `cognitive_agent.py:3015`, `:3025-3045` (`:3028` `"params": intent.params`), `:3068-3074` |
| `IntentMessage` is a dataclass with no `get`, and `params` defaults to a dict | `src/probos/types.py:58`, `:62` |
| `act` returns the LLM's text, and `handle_intent` passes it through as `IntentResult.result` | `cognitive_agent.py:6737`, `:8063-8068` |
| L4 and L5 make no LLM call for `diagnose_system`: `llm_output` is `""` | `cognitive_agent.py:4446-4457`; `diagnostic_levels.py:43-55` (`llm_tier` is `None` for L4 and L5, `fast` for L3 and L2, `deep` for L1) |
| The panel calls `.get` on its argument and puts the values in markup-parsed `str` cells | `src/probos/experience/panels.py:654`, `:675-694`; `Text` is already imported at `:20` |
| Rich parses a `str` renderable as markup. A closing tag that matches no open tag raises `MarkupError`, whose message quotes the tag | `.venv/Lib/site-packages/rich/console.py:1320-1323`; `rich/markup.py:162-169` |
| `rich.markup.escape` puts a backslash before a tag. Two backslashes before a tag parse as one literal backslash followed by a **live** tag | `rich/markup.py:48-70`, `:88-98` |
| `extract_json` raises `ValueError` when no object is found. Its fenced branch returns whatever `json.loads` returns, which can be a list | `src/probos/utils/json_extract.py:17`, `:34-37`, `:79` |
| The user message carries `Parameters: {params}` and `Context: {context}` | `cognitive_agent.py:11567-11571` |
| The tests' `stub_super_perceive` replaces the base with `dict(intent)`, which keeps a top-level `level` that the real base drops | `tests/test_ad700_multi_level_diagnostics.py:73-84` |
| The slash-command tests mock the agent, and its `result` is a dict | `tests/test_ad700a_diagnostic_slash_command.py:14-32` |
| `asyncio_mode = "auto"` | `pyproject.toml:181` |
| **Measured (your probe, `probe-b991-premise.out.txt`)** | Control: `medical_alert` succeeds with 1 call. Issue: `AttributeError: 'IntentMessage' object has no attribute 'get'` with 0 calls. With the first fault bypassed: `result` is a `str` at every level (`''` with 0 calls at L5 and L4; JSON text with 1 call on `fast` at L3 and L2, on `deep` at L1). The handler prints `Diagnostic error: 'str' object has no attribute 'get'` at L3 and L1, and a panel at L4. The real base `perceive` over `{'intent','level'}` keeps no `level` |

## 1. Problem

The `/diagnostic` command fails on every call (#1840). Two faults lie on one path.

**Fault 1: the level read.** `DiagnosticianAgent.perceive` calls `intent.get("level")` (`diagnostician.py:83`) on the argument. `handle_intent` gives it the `IntentMessage` built at `commands_diagnostic.py:66-69`, which has no `get`. The `AttributeError` propagates out of `handle_intent` before the Vitals scan or any LLM call (probe P1: 0 calls). The handler's `except` prints `Diagnostic error: 'IntentMessage' object has no attribute 'get'`.

**Fault 2: the result type.** The Diagnostician overrides only `__init__` and `perceive` (the whole file was read, `:61-148`). So `act` returns `{"result": decision.get("llm_output", "")}` (`cognitive_agent.py:6737`), and `IntentResult.result` is the LLM's text: `""` at L4 and L5, JSON text at L3 to L1 (probe P2). The handler passes that text to `render_diagnostic_result` (`commands_diagnostic.py:71-72`), which calls `.get` on it (`panels.py:654`). The probe measured `Diagnostic error: 'str' object has no attribute 'get'` at L3 and L1.

**Why the tests passed.**
- The `perceive` tests give a flat dict to a stubbed base that keeps every key (`test_ad700_multi_level_diagnostics.py:73-84`).
- The handler tests give a mocked agent whose result is a dict (`test_ad700a_diagnostic_slash_command.py:22-31`).
- Each half is tested; the seam between them is not.

**Fault 2b: the markup in the panel.** This becomes reachable once fault 2 is repaired. The panel's value cells are markup-parsed `str` (`panels.py:675-694`). An LLM value holding a stray closing tag such as `[/x]` raises `MarkupError` when the panel is printed (`rich/markup.py:167-169`). The handler's `except` then prints `f"[red]Diagnostic error: {e}[/red]"` (`commands_diagnostic.py:81`). The `MarkupError` message quotes `[/x]`, so that print raises again, and the error propagates out of a slash command that is documented never to propagate (`:74`). Test 13 measures the second print on its own, through an exception whose text holds `[/x]`.

## 2. Solution overview

1. **Fault 1.** `perceive` reads the level from the observation `super().perceive` already built, at `result["params"]["level"]`. Only when that is absent and the argument is a `dict` does it fall back to the argument's top-level `level`, the flat form that the base drops and the AD-700 tests use. `params` wins when both are present. The type hint becomes `Any`, as on the base (`cognitive_agent.py:3015`).
2. **Fault 2.** The handler turns the result into a diagnosis with one helper:
   - A dict passes through unchanged.
   - Anything else is turned into a string and parsed with the existing `extract_json`.
   - Text with no JSON object (or JSON that is not an object) gives an empty panel, followed by the raw text printed without markup.
   - A result with `success=False` prints `Diagnostic failed: <error>` and no panel.
   - At L4 and L5 (`level.llm_tier is None`) one line says there is no LLM analysis at this depth (AD-700c).
3. **Fault 2b.**
   - The panel's value cells become `rich.text.Text`, which is never parsed as markup.
   - Every handler line that prints text the handler did not write (the raw reply, the failure text, the exception text) is printed with `markup=False, emoji=False, highlight=False`, so it is shown as received (A1).

**Rejected heavier designs:**
- Making the base `perceive` copy top-level keys. That changes a shared contract used by 19 overrides and breaks AD-432/BF-698's rule that the dict branch adds nothing it was not given (`cognitive_agent.py:3060-3067`).
- A Diagnostician `act` override that returns a dict. That changes the type of `IntentResult.result` for every reader of the result.
- A metrics view for L4. That is new display work, recorded as #1820 item bf-991 F1.

## 3. Decisions

**D1. Where the level is read.**

| Rank | Option | Verdict |
|---|---|---|
| 1 (chosen) | `params["level"]` from the observation; if absent and `isinstance(intent, dict)`, `intent.get("level")`; `params` wins | Right for both shapes, one file, no shared contract |
| 2 | A helper that re-reads the raw argument in both shapes | Right, but repeats the base's `isinstance(IntentMessage)` normalisation |
| 3 | An `isinstance` guard only (`intent.get` on a dict, else the default) | **Wrong**: the command's level is dropped and every call runs at L3. This is mutation M2b |
| 4 | Base `perceive` copies top-level keys | Rejected, see section 2 |

`params` wins because the `IntentDescriptor` declares `level` under `params` (`diagnostician.py:48-56`), and the only producer sends it there (AV1). A `params` key whose value is `None` falls through to the flat form.

**D2. Parse in the handler**, not in the agent. The decision rank is in consult `87e8824a`. Text that holds no JSON object is shown, not swallowed: the Captain sees what the LLM said. The `isinstance(parsed, dict)` check covers the fenced branch of `extract_json`, which can return a list (`json_extract.py:34-37`).

**D3. Foreign text: `rich.markup.escape` is out; `Text` cells and `markup=False, emoji=False, highlight=False` are in.**
- Escaping the values in the handler fails for `evidence`, which the panel renders with `str(list)` (`panels.py:686`). The list's repr doubles the backslash that `escape` adds, and Rich reads two backslashes before a tag as one literal backslash followed by a live tag (`rich/markup.py:88-98`). The `MarkupError` stays.
- A `Text` cell is never parsed, whatever the value's type. The panel has one caller (AV2), so the change is contained.
- The handler's own three prints of foreign text use `markup=False` for the same reason, and `emoji=False, highlight=False` because `markup=False` stops only the markup parse: Rich still turns `:warning:` into a sign and, on a terminal, colours numbers, booleans and brackets (section 17). Tests 13, 11 and 10 cover the `except` line, the failure line and the raw-text line on a terminal console; test 12 covers the panel cells the same way.
- These are in BF-991 because they become reachable only once fault 2 is repaired (LLM text first reaches the panel through this change). The `except` line is the same handler's same rule; leaving it would also leave an inconsistency the Diff Reviewer would flag.

**D4. The L4/L5 line.** `No LLM analysis at this depth (AD-700c): <level> makes no LLM call.` It is printed after the panel, whenever `level.llm_tier is None`. The scan's metrics are not shown; that gap is item bf-991 F1 on #1820 (section 8.3).

**D5. Test construction: a real `DiagnosticianAgent` over your probe's counting double** (`MagicMock(complete=AsyncMock(return_value=MagicMock(content=..., tier="fast", error=None)))`). The agent gets a two-method runtime double (`registry.all`, `registry.get_by_pool`).
- Not the `__new__` pattern of `test_ad700c_diagnostician_tier_routing.py:14-39`: it skips `__init__` and calls `_decide_via_llm` directly. That is the half-chain that hid both faults.
- Not `MockLLMClient` (`llm_client.py:2697`): its reply depends on a regex table it registers itself (`:3070`) and on special cases for arbiter and reflection prompts (`:2949-2966`), so the test would not control the reply.
- The probe's construction is the one measured: P0 succeeds with exactly one call.
- Each test makes its own agent with a unique id, so the tests share no state.

**D6. Corrections to the issue's acceptance.** It says "L1 and L2 reach the deeper tiers"; in fact L2 is `fast` like L3, and only L1 is `deep`. L4 makes **zero** LLM calls (it does scan). These tests assert the corrected facts.

**D7. Roadmap: no row.** The Bug Tracker lists only "Open, filed but deliberately not fixed" bugs (`docs/development/roadmap.md:1139`), as BF-987's contract also recorded.

**D8. Ledger: the offline generator** (`-P scripts/gen_ad_ledger.py`, as in BF-987 and BF-990). `--online` would also pull unrelated changes to the GitHub issue layer into this PR's diff. The local trackers carry BF-991.

## 4. Milestones and focused gates

**M1 focused gate** (run after step 3, and as the premise gate's run after step 2):

`d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf991_diagnostic_intent_message.py tests/test_ad700_multi_level_diagnostics.py tests/test_diagnostician.py tests/test_ad700a_diagnostic_slash_command.py -q -n 0`

**M2:** after 7.5 to 7.8, run 7.9's generator, then `--check`, then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

## 5. Consumers of every value this changes

| Changed | Consumer | Expectation |
|---|---|---|
| D2: how `level` is read | `cognitive_agent.py:4448` (AD-700c short-circuit), `:4715-4716` (AD-700b journal tags), `:13042` (`_resolve_tier_for_observation`) | They read `level`, `level_rank` and `level_llm_tier`, which `perceive` still writes under the same keys. Unchanged |
| D1: `perceive(self, intent: Any)` | `_run_cognitive_lifecycle` (`:7609`); `test_ad700_multi_level_diagnostics.py` (stubbed base, flat dicts); `test_diagnostician.py:51,67,74,85` (real base, `{"intent","params"}`) | Type hint only. The flat form reaches the fallback; a `params` dict without `level` gives L3 as before |
| C3/C4: handler output | The Captain's shell; `test_ad700a_diagnostic_slash_command.py` | Its default result is a dict, so it passes through. Its `MagicMock` `success` is truthy, so no failure line. `:109-116` still finds `Diagnostic error` |
| P1: `render_diagnostic_result` cells | Its only caller, `commands_diagnostic.py:72` (AV2) | Same text and labels; values are no longer markup |
| `medical_alert` path | `diagnostician.py:82` | Untouched: the override acts only when `intent == "diagnose_system"` |

## 6. Tests (new file `tests/test_bf991_diagnostic_intent_message.py`)

| # | Name | Asserts |
|---|---|---|
| 1 | `test_l3_message_makes_one_fast_call_with_the_scan_in_its_request` | Success; 1 call; tier `fast`; the request contains `Diagnostic depth: L3` and `W-1840`; `scan_now` awaited once |
| 2 | `test_l5_message_makes_no_call_and_no_scan` | Success; 0 calls; `scan_now` not awaited |
| 3 | `test_l1_message_requests_the_deep_tier` | Success; 1 call; tier `deep`; `Diagnostic depth: L1` and `W-1840` in the request |
| 4 | `test_l4_message_scans_without_a_call` | Success; `scan_now` awaited once; 0 calls |
| 5 | `test_the_focus_reaches_the_request` | `focus-bf991` is in the request |
| 6 | `test_a_flat_dict_level_survives_the_real_base_perceive` | Premise: the real base drops a top-level `level`. Then `out["level"] == "L5"`, tier `None` |
| 7 | `test_params_win_over_a_top_level_level` | `params.level=L1` with top-level `L5` gives L1, `deep` |
| 8 | `test_the_handler_prints_the_parsed_diagnosis` | Real handler, L3: `marker-1840` and `Diagnostic L3` shown; no `Diagnostic error`; 1 call |
| 9 | `test_the_handler_at_l4_prints_the_panel_and_the_no_llm_line` | `Diagnostic L4`, the AD-700c line, no error, 0 calls, scan awaited once |
| 10 | `test_a_reply_that_is_not_a_diagnosis_is_printed_as_text[text-with-brackets, fenced-json-array]` | The empty panel (`Root cause`) and the raw text, unbroken on a terminal console; no error |
| 11 | `test_a_failed_result_prints_its_error_and_no_panel` | `Diagnostic failed: boom [/x] :warning: 42 True` unbroken on a terminal console; no `Root cause` |
| 12 | `test_llm_text_in_the_panel_is_shown_as_text_not_markup` | `[/x] :warning: 42 True stray tag` and `[core]` unbroken on a terminal console; no error |
| 13 | `test_an_error_text_that_looks_like_markup_is_printed_not_raised` | `Diagnostic error: bad [/x] :warning: 42 True tag` unbroken on a terminal console; nothing propagates |

**Predicted red/green** (14 cases):

| # | Base (only 7.1 added) | After D1-D2 only (premise gate) | After M1 and A1 |
|---|---|---|---|
| 1-5 | red: `AttributeError: 'IntentMessage' object has no attribute 'get'` raised by `handle_intent` | green | green |
| 6 | **green** (the flat dict works on the base) | green | green |
| 7 | red (`L5` != `L1`) | green | green |
| 8 | red (`Diagnostic error: 'IntentMessage' ...`) | **red: `Diagnostic error: 'str' object has no attribute 'get'`** (the premise gate) | green |
| 9 | red (`'IntentMessage'` error) | red (panel shown, AD-700c line absent) | green |
| 10 x2 | red | red (`'str' ... 'get'`) | green |
| 11 | red (empty panel shown, no failure line) | red | green |
| 12 | red | red (`'str' ... 'get'`) | green |
| 13 | red: `MarkupError` propagates from `cmd_diagnostic` | red | green |

Base: 13 red, 1 green. After D1-D2: 7 green, 7 red. After M1 and A1: 14 green. The three existing files stay green in all three columns, with one exception: the M3 mutant (section 10) turns three `test_ad700_*` cases red.

## 7. The contract

### 7.1 New file: `tests/test_bf991_diagnostic_intent_message.py` (M1, written first)

```python
"""BF-991 (#1840): ``/diagnostic`` reaches the Diagnostician at the level it asks for, and prints the diagnosis.

Two faults on one path. ``DiagnosticianAgent.perceive`` read the level with
``intent.get("level")`` on the ``IntentMessage`` the command sends, which has no
``get``. Past that, ``IntentResult.result`` is the LLM's text (``CognitiveAgent.act``),
and the handler rendered it as if it were a dict.

These tests drive the real path: a real ``DiagnosticianAgent`` over a counting LLM
double (the construction the BF-991 premise probe measured), through
``handle_intent`` and through the real ``cmd_diagnostic`` handler. Each half was
tested before (``perceive`` over a stubbed base, the handler over a mocked agent
returning a dict); the seam between them was not.
"""

from __future__ import annotations

import uuid
from io import StringIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.agents.medical.diagnostician import DiagnosticianAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.experience.commands.commands_diagnostic import cmd_diagnostic
from probos.types import IntentMessage, IntentResult

_MARKER = "W-1840"
_FOCUS = "focus-bf991"
# Text Rich rewrites unless told not to: an emoji code, and a number and a boolean it highlights on a terminal.
_LITERAL = ":warning: 42 True"
_DIAG_JSON = (
    '{"severity": "high", "category": "agent", "affected_components": ["x"], '
    '"root_cause": "marker-1840", "evidence": [], "recommended_treatment": "none", '
    '"treatment_intent": "medical_tune", "treatment_params": {}}'
)


class _Vitals:
    """The Vitals Monitor as ``perceive`` finds it: by ``agent_type`` in ``registry.all()``."""

    agent_type = "vitals_monitor"

    def __init__(self) -> None:
        self.scan_now = AsyncMock(return_value={"recent_history": [{"marker": _MARKER}]})


class _Registry:
    def __init__(self, vitals: _Vitals) -> None:
        self._vitals = vitals

    def all(self) -> list[Any]:
        return [self._vitals]

    def get_by_pool(self, pool: str) -> list[Any]:
        """The base agent's AD-568d reads ask for the counselor pool inside a ``try``; there is none."""
        return []


def _llm(reply: str) -> MagicMock:
    """The premise probe's counting double: each request is recorded on ``complete``; the reply is ``reply``."""
    return MagicMock(complete=AsyncMock(return_value=MagicMock(content=reply, tier="fast", error=None)))


def _agent(reply: str = _DIAG_JSON) -> tuple[DiagnosticianAgent, MagicMock, _Vitals]:
    vitals = _Vitals()
    llm = _llm(reply)
    agent = DiagnosticianAgent(
        agent_id=f"diag-bf991-{uuid.uuid4().hex[:8]}",
        pool="medical",
        llm_client=llm,
        runtime=SimpleNamespace(registry=_Registry(vitals)),
    )
    return agent, llm, vitals


def _requests(llm: MagicMock) -> list[Any]:
    return [call.args[0] for call in llm.complete.await_args_list]


def _sent(request: Any) -> str:
    """All the text a request sends: the prompt, the system prompt and any messages."""
    return f"{request.prompt}\n{request.system_prompt}\n{request.messages}"


async def _diagnose(agent: DiagnosticianAgent, level: str, focus: str = "") -> IntentResult | None:
    return await agent.handle_intent(
        IntentMessage(intent="diagnose_system", params={"level": level, "focus": focus})
    )


def _shell(agent: Any, *, terminal: bool = False) -> tuple[SimpleNamespace, Console, StringIO]:
    """The ship as the handler reads it: one healthy agent in the ``medical_diagnostician`` pool.

    ``terminal=True`` gives a console that writes ANSI codes whatever the environment says,
    so Rich's styles, and any highlighting, show in the buffer.
    """
    pool = SimpleNamespace(healthy_agents=[agent.id], registry=SimpleNamespace(get=lambda _agent_id: agent))
    buf = StringIO()
    if terminal:
        console = Console(
            file=buf, force_terminal=True, color_system="standard", legacy_windows=False, no_color=False, width=120
        )
    else:
        console = Console(file=buf, force_terminal=False, width=120)
    return SimpleNamespace(pools={"medical_diagnostician": pool}), console, buf


# -- the agent: the level the message carries reaches the LLM call (tests 1-5) --


async def test_l3_message_makes_one_fast_call_with_the_scan_in_its_request() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L3")
    assert result is not None and result.success, result
    assert llm.complete.await_count == 1
    (request,) = _requests(llm)
    assert request.tier == "fast"
    assert "Diagnostic depth: L3" in _sent(request)
    assert _MARKER in _sent(request)
    vitals.scan_now.assert_awaited_once()


async def test_l5_message_makes_no_call_and_no_scan() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L5")
    assert result is not None and result.success, result
    assert llm.complete.await_count == 0
    vitals.scan_now.assert_not_awaited()


async def test_l1_message_requests_the_deep_tier() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L1")
    assert result is not None and result.success, result
    assert llm.complete.await_count == 1
    (request,) = _requests(llm)
    assert request.tier == "deep"
    assert "Diagnostic depth: L1" in _sent(request)
    assert _MARKER in _sent(request)


async def test_l4_message_scans_without_a_call() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L4")
    assert result is not None and result.success, result
    vitals.scan_now.assert_awaited_once()
    assert llm.complete.await_count == 0


async def test_the_focus_reaches_the_request() -> None:
    agent, llm, _ = _agent()
    await _diagnose(agent, "L3", focus=_FOCUS)
    (request,) = _requests(llm)
    assert _FOCUS in _sent(request)


# -- the flat-dict form, through the real base perceive (tests 6-7) -------------


async def test_a_flat_dict_level_survives_the_real_base_perceive() -> None:
    agent = DiagnosticianAgent(agent_id=f"diag-bf991-{uuid.uuid4().hex[:8]}", pool="medical")
    flat = {"intent": "diagnose_system", "level": "L5"}
    base = await CognitiveAgent.perceive(agent, dict(flat))
    assert "level" not in base, "premise: the base's dict branch keeps no top-level level"
    out = await agent.perceive(dict(flat))
    assert out["level"] == "L5"
    assert out["level_llm_tier"] is None


async def test_params_win_over_a_top_level_level() -> None:
    agent = DiagnosticianAgent(agent_id=f"diag-bf991-{uuid.uuid4().hex[:8]}", pool="medical")
    out = await agent.perceive({"intent": "diagnose_system", "params": {"level": "L1"}, "level": "L5"})
    assert out["level"] == "L1"
    assert out["level_llm_tier"] == "deep"


# -- the real handler over the real agent (tests 8-13) --------------------------


async def test_the_handler_prints_the_parsed_diagnosis() -> None:
    agent, llm, _ = _agent()
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "marker-1840" in out, out
    assert "Diagnostic L3" in out, out
    assert llm.complete.await_count == 1


async def test_the_handler_at_l4_prints_the_panel_and_the_no_llm_line() -> None:
    agent, llm, vitals = _agent()
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L4")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "Diagnostic L4" in out, out
    assert "No LLM analysis at this depth (AD-700c)" in out, out
    assert llm.complete.await_count == 0
    vitals.scan_now.assert_awaited_once()


@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        (f"Ship nominal [x] {_LITERAL} no JSON here", f"Ship nominal [x] {_LITERAL} no JSON here"),
        ("```json\n[1, 2]\n```", "[1, 2]"),
    ],
    ids=["text-with-brackets", "fenced-json-array"],
)
async def test_a_reply_that_is_not_a_diagnosis_is_printed_as_text(reply: str, shown: str) -> None:
    agent, llm, _ = _agent(reply)
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "Root cause" in out, out
    assert shown in out, out
    assert llm.complete.await_count == 1


async def test_a_failed_result_prints_its_error_and_no_panel() -> None:
    failed = IntentResult(
        intent_id="i-bf991", agent_id="diag-bf991", success=False, error=f"boom [/x] {_LITERAL}"
    )
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(return_value=failed))
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert f"Diagnostic failed: boom [/x] {_LITERAL}" in out, out
    assert "Root cause" not in out, out


async def test_llm_text_in_the_panel_is_shown_as_text_not_markup() -> None:
    reply = (
        '{"severity": "low", "category": "agent", "root_cause": "[/x] '
        + _LITERAL
        + ' stray tag", "evidence": ["pool [core] low"], "recommended_treatment": "none"}'
    )
    agent, _, _ = _agent(reply)
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert f"[/x] {_LITERAL} stray tag" in out, out
    assert "[core]" in out, out


async def test_an_error_text_that_looks_like_markup_is_printed_not_raised() -> None:
    error = RuntimeError(f"bad [/x] {_LITERAL} tag")
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(side_effect=error))
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert f"Diagnostic error: bad [/x] {_LITERAL} tag" in out, out
```

### 7.2 `src/probos/agents/medical/diagnostician.py` (M1)

**D1.** SEARCH (once, `:66-69`):
```python
    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Enrich diagnose_system intents with live metrics from VitalsMonitor (AD-350).

        AD-700: Honor the ``level`` parameter (L5..L1). Shallower levels skip
```
REPLACE:
```python
    async def perceive(self, intent: Any) -> dict[str, Any]:
        """Enrich diagnose_system intents with live metrics from VitalsMonitor (AD-350).

        ``intent`` is an ``IntentMessage`` (from ``handle_intent``) or a dict, as on
        the base ``CognitiveAgent.perceive`` (BF-991).

        AD-700: Honor the ``level`` parameter (L5..L1). Shallower levels skip
```

**D2.** SEARCH (once, `:82-84`):
```python
        if result.get("intent") == "diagnose_system":
            level = parse_level(intent.get("level"))
            result["level"] = level.value
```
REPLACE:
```python
        if result.get("intent") == "diagnose_system":
            # BF-991 (#1840): read the level from the observation super().perceive
            # built. For an IntentMessage (what /diagnostic sends) it is under
            # ``params``, and the message has no ``.get``. The base's dict branch
            # keeps only intent/params/context, so a flat dict's top-level
            # ``level`` is read from the argument; ``params`` wins when both have one.
            params = result.get("params")
            raw_level = params.get("level") if isinstance(params, dict) else None
            if raw_level is None and isinstance(intent, dict):
                raw_level = intent.get("level")
            level = parse_level(raw_level)
            result["level"] = level.value
```

### 7.3 `src/probos/experience/commands/commands_diagnostic.py` (M1)

**C1.** SEARCH (once, `:17-24`):
```python
import logging
from typing import TYPE_CHECKING

from rich.console import Console

from probos.agents.medical.diagnostic_levels import parse_level
from probos.experience import panels
from probos.types import IntentMessage
```
REPLACE:
```python
import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console

from probos.agents.medical.diagnostic_levels import parse_level
from probos.experience import panels
from probos.types import IntentMessage
from probos.utils.json_extract import extract_json
```

**C2.** SEARCH (once, `:35-39`):
```python
    "Examples: /diagnostic | /diagnostic L2 | /diagnostic L1 trust_network"
)


async def cmd_diagnostic(
```
REPLACE:
```python
    "Examples: /diagnostic | /diagnostic L2 | /diagnostic L1 trust_network"
)


def _diagnosis_from_result(result: Any) -> tuple[dict[str, Any], str]:
    """BF-991: the diagnosis dict in an IntentResult's ``result``, and any text that is not one.

    ``CognitiveAgent.act`` returns the LLM's text, so ``result`` is a str: the JSON
    the Diagnostician was told to write at L3..L1, and "" at L4/L5, which make no
    LLM call (AD-700c). A dict passes through unchanged. Returns
    ``(diagnosis, unparsed_text)``; the second item is "" unless the text holds no
    JSON object.
    """
    if isinstance(result, dict):
        return result, ""
    text = "" if result is None else str(result)
    if not text.strip():
        return {}, ""
    try:
        parsed = extract_json(text)
    except ValueError:
        return {}, text
    if not isinstance(parsed, dict):
        return {}, text
    return parsed, ""


async def cmd_diagnostic(
```

**C3.** SEARCH (once, `:68-73`):
```python
                params={"level": level.value, "focus": focus},
            )
        )
        result = intent_result.result if intent_result else None
        panel = panels.render_diagnostic_result(result or {}, level=level)
        console.print(panel)
```
REPLACE:
```python
                params={"level": level.value, "focus": focus},
            )
        )
        if intent_result is not None and not intent_result.success:
            console.print(
                f"Diagnostic failed: {intent_result.error or 'no error given'}",
                style="red",
                markup=False,
                emoji=False,
                highlight=False,
            )
            return
        diagnosis, unparsed = _diagnosis_from_result(
            intent_result.result if intent_result else None
        )
        panel = panels.render_diagnostic_result(diagnosis, level=level)
        console.print(panel)
        if unparsed:
            # The LLM's own words, shown as received: no markup, emoji codes or highlighting.
            console.print("The Diagnostician's reply is not a JSON diagnosis:", style="yellow")
            console.print(unparsed, markup=False, emoji=False, highlight=False)
        if level.llm_tier is None:
            console.print(
                f"No LLM analysis at this depth (AD-700c): {level.value} makes no LLM call.",
                style="dim",
                markup=False,
            )
```

**C4.** SEARCH (once, `:78-81`):
```python
            focus,
            e,
        )
        console.print(f"[red]Diagnostic error: {e}[/red]")
```
REPLACE:
```python
            focus,
            e,
        )
        # BF-991: the error text is foreign text, printed as received; as markup, a "[/x]" in it raises again here.
        console.print(f"Diagnostic error: {e}", style="red", markup=False, emoji=False, highlight=False)
```

### 7.4 `src/probos/experience/panels.py` (M1, P1)

SEARCH (once, `:675-694`):
```python
    table.add_row("Severity", f"[{severity_color}]{severity}[/{severity_color}]")
    table.add_row("Category", str(result.get("category") or "--"))

    affected = result.get("affected_components") or []
    if isinstance(affected, list):
        affected_str = ", ".join(str(a) for a in affected) if affected else "--"
    else:
        affected_str = str(affected)
    table.add_row("Affected", affected_str)

    table.add_row("Root cause", str(result.get("root_cause") or "--"))
    table.add_row("Evidence", str(result.get("evidence") or "--"))
    table.add_row(
        "Recommended treatment",
        str(result.get("recommended_treatment") or "--"),
    )
    table.add_row(
        "Treatment intent",
        str(result.get("treatment_intent") or "--"),
    )
```
REPLACE:
```python
    # BF-991 (#1840): every value below is LLM text, so each cell is a ``Text``
    # and is never parsed as Rich markup (a stray closing tag such as "[/x]"
    # raises MarkupError when rendered as markup).
    table.add_row("Severity", Text(severity, style=severity_color))
    table.add_row("Category", Text(str(result.get("category") or "--")))

    affected = result.get("affected_components") or []
    if isinstance(affected, list):
        affected_str = ", ".join(str(a) for a in affected) if affected else "--"
    else:
        affected_str = str(affected)
    table.add_row("Affected", Text(affected_str))

    table.add_row("Root cause", Text(str(result.get("root_cause") or "--")))
    table.add_row("Evidence", Text(str(result.get("evidence") or "--")))
    table.add_row(
        "Recommended treatment",
        Text(str(result.get("recommended_treatment") or "--")),
    )
    table.add_row(
        "Treatment intent",
        Text(str(result.get("treatment_intent") or "--")),
    )
```

### 7.5 `PROGRESS.md`: the new entry (M2)

SEARCH (whole line, once, `:1`):
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-991 (2026-11-20), #1840 -- `/diagnostic` reaches the Diagnostician at the level it asks for, and the handler prints the diagnosis the LLM returns.** `DiagnosticianAgent.perceive` read the level with `intent.get("level")` on the `IntentMessage` the command sends, so every call raised `AttributeError` before the Vitals scan or any LLM call. It now reads the level from the observation's `params`, falls back to a flat dict's top-level `level` (the form the AD-700 tests use, which the base `perceive` drops), and `params` wins when both are present. Past that fault, `IntentResult.result` is the LLM's text, and the handler rendered it as if it were a dict, printing `Diagnostic error: 'str' object has no attribute 'get'` at L3 and L1. The handler now parses the text with `extract_json`, prints a reply that holds no JSON object as plain text under an empty panel, prints `Diagnostic failed: <error>` for a failed result, and adds a no-LLM line at L4 and L5 (AD-700c). The panel's value cells are `Text`, and the handler prints foreign text with `markup=False`, so LLM or error text is never read as Rich markup. Measured by `tests/test_bf991_diagnostic_intent_message.py` (14 cases) over a real Diagnostician, a counting LLM double and a `scan_now` double: L3 makes one `fast` call whose request carries the depth hint, the focus and `scan_now`'s output; L1 makes one `deep` call; L4 scans with no call; L5 does neither; the real handler prints the parsed fields. The issue's acceptance is corrected: L2 is `fast` like L3, only L1 is `deep`, and L4 makes no LLM call. No live `/diagnostic` run was made. The L4 metrics the Captain does not see are item bf-991 F1 of #1820. Contract `prompts/bf-991-diagnostic-intent-message.md`.
```

### 7.6 `PROGRESS.md`: the BF-990 amendment (M2)

**For the pair tool:** line 3 (BF-990's paragraph) is one very long line, so this pair is a **substring replacement inside that line**. The SEARCH occurs exactly once in the file (`grep -c` gives 1). Neither SEARCH nor REPLACE holds a newline, and the line's CRLF ending is untouched. Apply it after or before 7.5: 7.5's text does not contain this SEARCH.

SEARCH (substring):
```text
on the `IntentMessage` it is sent: BF-991, #1840). Params, severity
```
REPLACE:
```text
on the `IntentMessage` it is sent: BF-991, #1840). [Amended by BF-991 (2026-11-20): that path now runs; over a counting LLM double and a `scan_now` double, the L3 and L1 requests carry `scan_now`'s output, L4 scans with no LLM call and L5 does neither.] Params, severity
```

### 7.7 `DECISIONS.md`: the new entry (M2)

SEARCH (whole line, once, `:1661`):
```markdown
### BF-990 -- The qualification-drift medical alert is edge-triggered on the critical reports' identities (2026-11-20, #1839)
```
REPLACE:
```markdown
### BF-991 -- /diagnostic reads the level from the message's params; the handler parses the LLM's text (2026-11-20, #1840)

- *Mechanism.* `DiagnosticianAgent.perceive` read the level with `intent.get("level")` on its argument; `handle_intent` passes the `IntentMessage` that `/diagnostic` builds, which has no `get`, so every call failed before the Vitals scan or an LLM call. Past that, `CognitiveAgent.act` returns the LLM's text (`{"result": llm_output}`), so `IntentResult.result` is a str (empty at L4 and L5, AD-700c), and the handler gave it to a panel that calls `.get`. The tests covered each half: `perceive` over a stubbed base that keeps every key, and the handler over a mocked agent whose result is a dict.
- *Where the level is read.* From the observation's `params` (what `super().perceive` built); only when that is absent and the argument is a dict, from its top-level `level`, which the base's dict branch drops; `params` wins when both are present, because the `IntentDescriptor` declares `level` there and the only producer sends it there. Rejected: an `isinstance` guard alone (the command's level is dropped and every call runs at L3); re-reading the raw argument in both shapes (repeats the base's normalisation); copying top-level keys in the base `perceive` (a contract shared by 19 overrides, and AD-432/BF-698's rule that the dict branch adds nothing it was not given).
- *The handler.* A dict result passes through; other results are parsed with `extract_json`. A reply that holds no JSON object (or JSON that is not an object) is printed as plain text under an empty panel; a failed result prints `Diagnostic failed: <error>` and no panel; L4 and L5 print one line saying no LLM analysis is made at that depth. Rejected: a Diagnostician `act` override that returns a dict (it changes the type of `IntentResult.result` for every reader).
- *Markup.* The panel's value cells are `rich.text.Text`, and the handler prints the reply, the failure text and the exception text with `markup=False`. Rejected: `rich.markup.escape` on the values, because `evidence` is rendered with `str(list)`, whose repr doubles the escape's backslash, which Rich reads as a literal backslash before a live tag.
- *Scope.* The handler parse and the markup repair were added to BF-991 (consult `87e8824a`): they are reachable only once the first fault is repaired, and the user-visible defect is the same. The L4 scan's metrics still do not reach the Captain (item bf-991 F1 of #1820).
- *Decided by the Architect.* None of the six conditions is met: it repairs a Captain-run command; at most one LLM call per invocation, as AD-700 and AD-700c designed (L1 `deep`, L2 and L3 `fast`, none at L4 and L5); no new spend path, schema, control or boundary.
- *Reversal.* Revert the BF-991 commits.

### BF-990 -- The qualification-drift medical alert is edge-triggered on the critical reports' identities (2026-11-20, #1839)
```

### 7.8 `DECISIONS.md`: the BF-990 amendment (M2)

**For the pair tool:** a whole-line replacement of `:1667`, once (`grep -c` gives 1). Apply it after or before 7.7: 7.7's text does not contain this line.

SEARCH (whole line):
```markdown
- *Not in `metrics`.* `scan_now` returns the window as `recent_history`, and `info()` reports the last metrics. `DiagnosticianAgent.perceive` would JSON-dump the window into the `diagnose_system` context, but that path fails on the `IntentMessage` the `/diagnostic` command sends (BF-991, #1840), so today no LLM context sees it; the Diagnostician sees only a `medical_alert`'s params.
```
REPLACE:
```markdown
- *Not in `metrics`.* `scan_now` returns the window as `recent_history`, and `info()` reports the last metrics. `DiagnosticianAgent.perceive` would JSON-dump the window into the `diagnose_system` context, but that path fails on the `IntentMessage` the `/diagnostic` command sends (BF-991, #1840), so today no LLM context sees it [amended by BF-991, 2026-11-20: that path now runs, and over a counting LLM double and a `scan_now` double the L3 and L1 requests carry `scan_now`'s output, a `recent_history` marker included; L4 scans with no LLM call and L5 does neither]; the Diagnostician sees only a `medical_alert`'s params.
```

### 7.9 Generated: the ledger pair (M2)

After 7.5 to 7.8, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` (whose `:32` now shows next free BF-991) and `docs/development/ad-ledger-snapshot.json`. Both go in M2's commit; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`. **`roadmap.md`: no row** (D7).

## 8. Issue texts (the orchestrator posts these; nothing here edits GitHub)

### 8.1 Comment on #1840 (at merge)

> Fixed by BF-991 (PR #...). There were two faults on the same path.
>
> 1. `DiagnosticianAgent.perceive` read the level with `intent.get("level")` on the `IntentMessage` the command sends. It now reads `params["level"]` from the observation the base `perceive` builds, and falls back to a flat dict's top-level `level`. The base drops that key, which is why the AD-700 tests passed only through their stub. `params` wins when both are present.
> 2. Past that, `IntentResult.result` is the LLM's text (`CognitiveAgent.act`), and the handler rendered it as a dict. The orchestrator's probe of 2026-11-20 measured `Diagnostic error: 'str' object has no attribute 'get'` at L3 and L1. The handler now parses the text with `extract_json`. A reply with no JSON object is printed as plain text under an empty panel, a failed result prints `Diagnostic failed: <error>`, and L4 and L5 add a no-LLM line (AD-700c). LLM text and error text are shown as text, never as Rich markup.
>
> Evidence: `tests/test_bf991_diagnostic_intent_message.py` (14 cases), run over a real Diagnostician, a counting LLM double and a `scan_now` double:
> - L3 makes one `fast` call whose request carries the depth hint, the focus and the scan's output.
> - L1 makes one `deep` call.
> - L4 scans and makes no call; L5 does neither.
> - The flat-dict form survives the real base `perceive`, and `params` wins over it.
> - The real handler prints the parsed fields, shows a reply that is not a diagnosis as text, and prints nothing as markup.
>
> One acceptance line is corrected: L2 is `fast` like L3, only L1 is `deep`, and L4 makes no LLM call. Not shown: a live `/diagnostic` run (an optional smoke test for the Captain). The L4 scan's metrics still do not reach the Captain; that is item bf-991 F1 on #1820.

### 8.2 Cross-reference comment on #507 (closed, stays closed)

> Cross-reference: the `/diagnostic` command this issue added failed on every call on the trees measured for #1840 (`fc9b9a6f`, `3331b4ac`). The Diagnostician read the level with `.get` on the `IntentMessage` the command sends, and the handler rendered the LLM's text as a dict. BF-991 (#1840, PR #...) repairs both. The AD-700a tests mocked the agent with a dict result, so the two halves were never exercised together; the new test drives the real handler over a real Diagnostician.

### 8.3 New item on #1820

`- [ ] **bf-991 F1 (P3, Low; a gap, not a regression): /diagnostic L4 runs the Vitals scan but shows the Captain none of it.** At L4 the Diagnostician awaits `VitalsMonitorAgent.scan_now()` and puts the metrics in the observation's `context` (`src/probos/agents/medical/diagnostician.py:90-113` before BF-991). L4 makes no LLM call (AD-700c, `src/probos/cognitive/cognitive_agent.py:4446-4457`), so `act` returns `""`, and the handler has nothing but that result to render. The panel shows `--` in every field, plus the line "No LLM analysis at this depth (AD-700c)". Evidence: `tests/test_bf991_diagnostic_intent_message.py::test_the_handler_at_l4_prints_the_panel_and_the_no_llm_line` (the scan is awaited once, 0 LLM calls, the panel and the line are printed). L5 skips the scan by design ("current value only") and shows nothing either. **Smallest repair:** for `diagnose_system` at L4, return the scan's metrics as the result (for example the short-circuit carrying the metrics it already has in the observation), and have `/diagnostic` render them as a metrics table under the panel. Decide at the same time whether L5 should take a cheap current-value read, which its spec implies.`

## 9. What this does NOT change

- The base `CognitiveAgent.perceive`, `act`, `handle_intent`, the AD-700c short-circuit, `_resolve_tier_for_observation`, the decision cache, `IntentResult` and `IntentMessage`.
- `diagnostic_levels.py` (`parse_level`, the tier map), `_INSTRUCTIONS`, the `IntentDescriptor`s, the `medical_alert` path, `vitals_monitor.py` (including its BF-990 comment at `:185-187`, which makes no claim about BF-991).
- The panel's header, labels and severity colours; `render_diagnostic_result`'s signature.
- The handler's usage text, the token parse, the pool lookup and the two "not available"/"not found" lines.
- The three existing test files. `prompts/bf-990-qualification-drift-alert-edge.md` (BF-990's historical contract). `roadmap.md`. No config, `EventType`, route, table or flag.

## 10. Mutation rows (one campaign; restore between rows; run only the listed killers)

The run after M1 with all edits applied is the campaign's base. Record the base tree and the sha256 of `diagnostician.py`, `commands_diagnostic.py`, `panels.py` and the new test file. On a later tree whose four files match, do not rerun; rerun a row only if its file differs. Rows M8 to M10 cover the decisions this contract adds (D3, D4). Rows M11a to M13b cover A1 (section 17).

| # | Site | Mutate to | Killed by |
|---|---|---|---|
| M1 | D2: the four lines `params = ...` to `level = parse_level(raw_level)` | `level = parse_level(intent.get("level"))` | 1, 2, 3, 4, 5, 7, 8, 9, 10[both], 12 |
| M2a | the same four lines | `level = parse_level(result.get("level"))` | 2, 3, 4, 6, 7, 9 (**not 1, 5 or 8**: L3 is the default) |
| M2b | the same four lines | `level = parse_level(intent.get("level") if isinstance(intent, dict) else None)` | 2, 3, 4, 7, 9 |
| M3 | D2: delete the two fallback lines (`if raw_level is None and isinstance(intent, dict):` and its body) | (deleted) | 6; `test_ad700_multi_level_diagnostics.py::test_perceive_l5_skips_vitals_scan`, `::test_perceive_l4_invokes_vitals_scan`, `::test_perceive_l1_uses_deep_tier` |
| M4 | D2: precedence | `raw_level = intent.get("level") if isinstance(intent, dict) else None` then `if raw_level is None and isinstance(params, dict): raw_level = params.get("level")` | 7 |
| M5 | C3: `diagnosis, unparsed = _diagnosis_from_result(...)` | `diagnosis, unparsed = (intent_result.result if intent_result else None) or {}, ""` | 8, 10[both], 12 |
| M6a | C2: `except ValueError: return {}, text` | `return {}, ""` | 10[text-with-brackets] |
| M6b | C2: `if not isinstance(parsed, dict): return {}, text` | (deleted) | 10[fenced-json-array] |
| M7 | C3: the `if intent_result is not None and not intent_result.success:` block | (deleted) | 11 |
| M8 | P1: the seven `Text(...)` wraps | the original `str` / markup cells | 12 |
| M9 | C4: `console.print(f"Diagnostic error: {e}", style="red", markup=False, emoji=False, highlight=False)` | `console.print(f"[red]Diagnostic error: {e}[/red]")` | 13 |
| M10 | C3: the `if level.llm_tier is None:` print | (deleted) | 9 |
| M11a | A1-1: the failure print | drop `emoji=False` | 11 |
| M11b | A1-1: the failure print | drop `highlight=False` | 11 |
| M12a | A1-2: the reply print | drop `emoji=False` | 10[text-with-brackets] |
| M12b | A1-2: the reply print | drop `highlight=False` | 10[both] |
| M13a | A1-3: the exception print | drop `emoji=False` | 13 |
| M13b | A1-3: the exception print | drop `highlight=False` | 13 |

**Unchanged-file check:** `git diff --stat <base> HEAD` lists exactly the three source files, the new test file, `PROGRESS.md`, `DECISIONS.md`, the ledger pair, and this prompt.

## 11. Verified Against Codebase (2026-11-20, `3331b4ac`; #1841's merge tree equals this tree)

```
src/probos/agents/medical/diagnostician.py
  :48-56 IntentDescriptor diagnose_system, params "level"   :59 _handled_intents
  :61-64 __init__ (setdefault pool; self._runtime = kwargs.get("runtime"))
  :66 async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
  :80 result = await super().perceive(intent)   :82 if result.get("intent") == "diagnose_system":
  :83 level = parse_level(intent.get("level"))   :90 if self._runtime and level is not DiagnosticLevel.L5:
  :93 for agent in self._runtime.registry.all():  :100 metrics = await vitals_agent.scan_now()
src/probos/experience/commands/commands_diagnostic.py
  :17-24 imports (TYPE_CHECKING only; no Any; no json_extract)   :35 "Examples: /diagnostic | ..."
  :39 async def cmd_diagnostic(   :55 runtime.pools.get("medical_diagnostician")
  :65-70 handle_intent(IntentMessage(intent="diagnose_system", params={"level": level.value, "focus": focus}))
  :71 result = intent_result.result if intent_result else None   :72 render_diagnostic_result(result or {}, level=level)
  :74 except ... noqa: BLE001 -- slash commands must not propagate   :81 console.print(f"[red]Diagnostic error: {e}[/red]")
src/probos/experience/panels.py :20 from rich.text import Text ; :641 def render_diagnostic_result( ; :654 result.get("severity") ; :675-694 add_row cells ; :686 str(result.get("evidence") ...)
src/probos/cognitive/cognitive_agent.py
  :3015 async def perceive(self, intent: Any) -> dict:  :3025 isinstance(intent, IntentMessage)  :3028 "params": intent.params
  :3068-3074 dict branch: intent / params / context / correlation_id
  :4446-4457 AD-700c short-circuit: llm_output "", tier_used "none"
  :4625-4635 LLMRequest(prompt=user_message, ..., tier=_per_call_tier or self._resolve_tier())
  :6737 _out = {"success": True, "result": decision.get("llm_output", "")}
  :7609 observation = await self.perceive(intent)   :8063-8068 IntentResult(... result=report.get("result"), error=report.get("error"))
  :8126 handle_intent  :11567-11571 Intent / Parameters / Context lines  :13042 _resolve_tier_for_observation
  :13111-13127 _decision_cache_enabled (False unless runtime.config.cognitive.decision_cache_enabled is True)
  _runtime reads on the decide/act path are hasattr/getattr- or try-guarded (:1784, :1791, :2745-2751, :7671-7674, :11590-11598, :11768-11777, :12724)
src/probos/utils/json_extract.py :17 def extract_json ; :34-37 fenced json.loads (any JSON type) ; :79 raise ValueError
src/probos/types.py :58 class IntentMessage ; :62 params default_factory=dict ; :78 class IntentResult ; :83 success ; :84 result ; :85 error
  :307 class LLMRequest ; :310 prompt ; :311 system_prompt ; :312 tier ; :323 messages
src/probos/agents/medical/diagnostic_levels.py :43-55 llm_tier (L5/L4 None, L3/L2 fast, L1 deep) ; :69 parse_level ; :82-83 None -> default
src/probos/cognitive/llm_client.py :2697 class MockLLMClient ; :2949-2966 arbiter special case ; :3070 re.search(pattern, match_text)
.venv rich/console.py :1320-1323 str renderable -> render_str(markup=...) ; rich/markup.py :48-70 escape ; :88-98 escapes divmod ; :162-169 MarkupError closing tag
src/probos/experience/shell.py :120 "/diagnostic" help ; :336 dispatch to commands_diagnostic.cmd_diagnostic
src/probos/startup/agent_fleet.py :353-364 medical_diagnostician pool created (target_size=1)
src/probos/agents/medical/vitals_monitor.py :222 async def scan_now ; :286 metrics["recent_history"] = list(self._window)
tests/test_ad700_multi_level_diagnostics.py :73-84 stub_super_perceive dict(intent) ; :116-123 L5 ; :127-133 L4 ; :137-143 L1 (flat dicts)
tests/test_diagnostician.py :50-51, :66-67, :73-77, :84-85 real base, {"intent","params"} dicts
tests/test_ad700a_diagnostic_slash_command.py :14-32 MagicMock agent, dict result ; :109-116 "Diagnostic error" on raise
tests/test_ad700c_diagnostician_tier_routing.py :14-39 __new__ construction ; :88-102 _decide_via_llm called directly
PROGRESS.md :1 "# ProbOS Progress" (grep -c 1) ; :3 substring "on the `IntentMessage` it is sent: BF-991, #1840). Params, severity" (grep -c 1)
DECISIONS.md :1661 ### BF-990 heading ; :1667 *Not in `metrics`* line (grep -c of its ASCII ending: 1)
docs/development/roadmap.md :1139 "**Open, filed but deliberately not fixed:**"
docs/development/open-ads-report.md :32 | BF | **BF-990** | **BF-991** | BF-990 | _(none)_ |
pyproject.toml :181 asyncio_mode = "auto"
git ls-files --eol: i/lf w/crlf for the five edited files
git diff --stat cc601a72 3331b4ac -- <the three source files, cognitive_agent.py, json_extract.py, the three test files>: empty
```

## Absence Verified (2026-11-20)

| | CLAIM | RUN | FOUND | HOLDS |
|---|---|---|---|---|
| AV1 | The slash command is the only producer of `diagnose_system` | Grep `diagnose_system` over `src` | `commands_diagnostic.py:67` (producer); readers at `cognitive_agent.py:4448`, `:4715-4716`, `:13046`; `journal.py:222` (comment); the Diagnostician (`:21`, `:49`, `:59`, `:67`, `:82`); `panels.py:646` (docstring) | yes |
| AV2 | `render_diagnostic_result` has one caller and no direct test | Grep `render_diagnostic_result` over `*.py` | `panels.py:641` (def); `commands_diagnostic.py:7` (docstring), `:72` (call); nothing in `tests/` | yes |
| AV3 | BF-991 is free for #1840 | `gh issue list --state all --search "BF-991 in:title"`; `git log --all -i --grep=BF-991`; Glob `prompts/bf-99*.md` | #1840 only; no commit; only `bf-990-...md` | yes |
| AV4 | The new test path is free | Glob `tests/test_bf991*` | none | yes |
| AV5 | The Diagnostician overrides only `__init__` and `perceive` | Read of `diagnostician.py:1-148` (whole file) | `__init__` (`:61`), `perceive` (`:66`) | yes |
| AV6 | Only `DiagnosticianAgent` calls `.get` on its `perceive` argument without a guard | the orchestrator's `audit\enum_perceive_overrides.py` (19 overrides, controls held) | that one | yes (the orchestrator's enumeration, not rerun here) |

## 12. Deterministic checks, resolved up front

- `MagicMock` is truthy, so `not intent_result.success` is `False` for `test_ad700a`'s default mock, and its dict result passes through C2 unchanged.
- `console.print` accepts `style` and `markup`. With `force_terminal=False`, the buffer holds plain text and no ANSI codes.
- With `_shell(..., terminal=True)`, styles are written as ANSI codes whatever `NO_COLOR`, `FORCE_COLOR`, `TTY_COMPATIBLE` or the platform say (`rich/console.py:707-712`, `:726-728`, `:939-940`). A line with one style is one code, the text and one reset (probe `probe_rich_literal.py`), so text printed with `highlight=False` and `emoji=False` stays unbroken in the buffer.
- Test 13's base red comes from the `MarkupError` raised by the `except` print (`rich/markup.py:167-169`; the message quotes `'[/x]'`).
- Test 12's M8 red: the panel print raises `MarkupError` and is caught; the C4 line then prints `Diagnostic error: ...` literally, so the assertion `"Diagnostic error" not in out` fails.
- Test 6's base column is green: the base reads `intent.get` on a dict, and that works. Test 6 exists to kill M2a and M3 and to pin the premise of the fallback.

## 13. Prior art and blind spots

- **Internal:** consult `87e8824a` (the ranked decisions); the orchestrator's premise probe (`G:\tmp\r1probe\probe_b991_premise.py`) and its perceive-override census. AD-432/BF-698 bound the base's dict branch, and this contract keeps it.
- **External:** none searched. This is ProbOS-specific plumbing with no outside design analogue. The third-party facts it relies on are Rich's: the markup parse and `escape`, read from the installed source, and the emoji and highlight passes that `markup=False` leaves on (`rich/console.py:1437-1462`), measured by the orchestrator's probe `probe_rich_literal.py`. No overdue reference project applies.
- **Blind spots, recorded:**
  - L4 shows no metrics: #1820 bf-991 F1.
  - L2 is not exercised by a test. It shares L3's tier and code path, and the probe measured it (1 call, `fast`).
  - Whether a live LLM writes JSON the panel fills is not shown; a live run by the Captain is optional.
  - A `diagnose_system` producer other than the slash command would also arrive as an `IntentMessage` and needs nothing new.

## 14. Diff Reviewer: properties to verify

1. `perceive` reads `params["level"]` from the observation first; reads the argument's top-level `level` only when that is `None` and the argument is a `dict`; never calls `.get` on a non-dict. Every key it writes (`level`, `level_rank`, `level_llm_tier`, `context`) is unchanged.
2. The handler never passes a non-dict to `render_diagnostic_result`. A failed result prints its error and returns before any panel. A reply with no JSON object is printed (not dropped), with `markup=False`.
3. Every handler print of foreign text (the reply, the failure text, the exception text) has `markup=False, emoji=False, highlight=False`, and every panel value cell is a `Text`. Tests 10 to 13 show that text unbroken on a terminal console. No `rich.markup.escape` is introduced.
4. No change outside the three source files, the new test, the two trackers and the ledger pair. BF-990's text is amended only by the bracketed insertions, and its prompt is untouched.
5. The tests drive the real `DiagnosticianAgent` (no `__new__`, no stubbed base) and the real `cmd_diagnostic`, and use no `MockLLMClient`. Test 6 asserts its premise. No assertion pins the faulty behaviour.
6. No commit subject carries an `AD-` or `BF-` token.

## 15. Acceptance criteria and the orchestrator's first-hand checks

**Acceptance:**
1. Section 6's three columns hold. The premise gate (test 8 red with `'str' object has no attribute 'get'` after D1-D2 only) was observed and recorded.
2. The M1 focused gate is green; every section 10 row is killed by its named tests.
3. Tracker texts are as in 7.5 to 7.8; the ledger is regenerated and `--check` is clean; no roadmap row.
4. One broad gate with a receipt; one PR that says `Refs #1840`; the texts of section 8 are posted after the merge.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**First-hand checks on the oracle tree, before the Builder starts:**

| O | Check | Expected |
|---|---|---|
| O1 | `git diff --stat 3331b4ac <oracle> -- src/probos/agents/medical/diagnostician.py src/probos/experience/commands/commands_diagnostic.py src/probos/experience/panels.py src/probos/cognitive/cognitive_agent.py src/probos/utils/json_extract.py PROGRESS.md DECISIONS.md` | Empty for the five source files. If main has moved, re-verify that each SEARCH still matches |
| O2 | Each of the 9 SEARCH blocks (D1, D2, C1-C4, P1, 7.5, 7.7, 7.8) plus 7.6's substring, matched against its file with line endings normalised | Exactly one match each |
| O3 | With only 7.1 added, run the new file at `-n 0` | 13 red and 1 green (test 6). Tests 1-5 fail with `AttributeError: 'IntentMessage' object has no attribute 'get'`; test 13 fails with `rich.errors.MarkupError` |
| O4 | Apply D1-D2 only and rerun | Tests 1-7 green, which also proves the two-method runtime double carries the real `handle_intent` to exactly 1 call at L3 and L1. Test 8 red, its output containing `Diagnostic error: 'str' object has no attribute 'get'`. If tests 1-5 fail for any other reason (an `AttributeError` on the runtime double, a call count other than 1), stop and report; do not loosen an assertion |
| O5 | Apply all of M1 and run the focused gate | All green; the three existing files unchanged and green |
| O6 | Both test 10 cases green after O5 | The reply reaches `IntentResult.result` unaltered. If a case fails because `act` changed the text, report the altered text; do not change the reply strings |
| O7 | `python -I -c "from rich.markup import render; render('[red]a [/x][/red]')"` | Raises `MarkupError` (the base-red reason of test 13 and the M8 kill) |
| O8 | Run section 10 against the M1 tree | Every row killed by exactly its listed tests. Record this as the campaign of record, with the four sha256 values |
| O9 | Re-run AV3 after #1841 merges | Only #1840; `open-ads-report.md:32` names BF-991 as next free |

## 16. The orchestrator's first-hand checks (2026-11-20, an oracle tree at `3331b4ac`, whose tree equals `e8e660b8`'s)

Every pair of section 7 was applied to a scratch worktree by `audit\oracle_apply_b991.py`, and every check of section 15 was run, before the Builder started. Results:

| O | Result |
|---|---|
| O1 | The oracle tree is `3331b4ac`. `git diff --stat cc601a72 3331b4ac` lists none of the five source files. `origin/main` moved to `e8e660b8`, the merge of #1841, and its tree (`3298a74c`) equals `3331b4ac`'s. |
| O2 | All 11 SEARCH blocks (D1, D2, C1 to C4, P1, 7.5, 7.6's substring, 7.7, 7.8) occur exactly once, in files that are CRLF throughout. |
| O3 | The new file alone: 13 failed, 1 passed (test 6). Tests 1 to 5 fail with `AttributeError: 'IntentMessage' object has no attribute 'get'`; test 7 with `assert 'L5' == 'L1'`; tests 8, 9 and 12 with `Diagnostic error: 'IntentMessage' ...`; test 11 shows the empty panel; test 13 fails with `rich.errors.MarkupError: closing tag '[/x]' at position 27 ...`. |
| O4 | D1 and D2 only: 7 passed (tests 1 to 7) and 7 failed (tests 8, 9, 10 twice, 11, 12, 13). Test 8 fails with `Diagnostic error: 'str' object has no attribute 'get'`: the premise gate holds. The sentence of section 6 that said "8 green, 6 red" is corrected to 7 and 7, which is what its own table gives. |
| O5 | All of M1: the focused gate of section 4 gives 58 passed (14 new and 44 in the three existing files); the existing files are unchanged. |
| O6 | Both cases of test 10 are green after O5. |
| O7 | `python -I -c "from rich.markup import render; render('[red]a [/x][/red]')"` raises `MarkupError: closing tag '[/x]' at position 7 doesn't match any open tag`. |
| O8 | The campaign of section 10 on the M1 tree (`audit\mutants_bf991.py`): 12 of 12 rows killed, each by exactly its listed tests and no other case. The base of the campaign, sha256: `diagnostician.py` `177e4babc4f6b94e10a33521a06d972251cee58698f1aebfde97f5df59f18b37`; `commands_diagnostic.py` `d1cbf030be8cebf4637a2aaa3185e1893ecc5701150d5fb6df4cd81880f2e7dd`; `panels.py` `b936a6e88e38176e523fabea521964621d989da321918e7fe5abfcdb52b08f7e`; `tests/test_bf991_diagnostic_intent_message.py` `ce6b68db647b5a35a33ec59383e1cac906f7bdc9dd4f440d4710eed99e0bceca`. A tree whose four files match these needs no rerun. |
| O9 | After #1841 merged: `gh issue list --state all --search "BF-991 in:title"` finds #1840 only; `git log --all -i --grep=BF-991` finds nothing; `prompts/bf-99*` holds only the BF-990 prompt; `open-ads-report.md` names BF-991 as next free. |

The premises, measured outside the tree (probe `probe_b991_premise.py`, premises asserted): the control `medical_alert` succeeds with 1 call; the issue's `AttributeError` is raised with 0 calls; with the first fault bypassed, `IntentResult.result` is a `str` at every level (`''` with 0 calls at L5 and L4; JSON text with 1 call on tier `fast` at L3 and L2, and on `deep` at L1); the real handler prints `Diagnostic error: 'str' object has no attribute 'get'` at L3 and L1 and a panel at L4; the real base `perceive` over `{'intent', 'level'}` keeps no `level`. The census (`enum_perceive_overrides.py`, controls held): of 19 `perceive` overrides in classes that descend from `CognitiveAgent`, only the Diagnostician calls `.get` on its argument without a guard.

## 17. Amendment A1: review round 1 (gpt-6.1-sol, REQUEST CHANGES), two findings

Review round 1 of `5ee64550` (8 minutes; `next/adq/b7/review-b991-r1.out.md`) found two things and nothing else. By execution it also found: 13 of 14 new cases fail on a full reversion; L5, L4, L3, L2 and L1 make 0, 0, 1, 1 and 1 LLM calls; the real `/diagnostic` dispatch works through the handler, the agent and the journal. The orchestrator reproduced finding 1 first-hand (probe `probe_rich_literal.py`, premises asserted). The decisions are the Architect's (read-only consult `7b52af2c`, 2026-11-20).

| Finding | Reviewer's class | Verified | Disposition |
|---|---|---|---|
| R1-1: `markup=False` stops markup parsing only. Rich still turns `:warning:` into a sign and, on a terminal, highlights numbers, booleans and brackets in the three prints of foreign text | P2, ordinary, regression of the new prints | Probe: `markup=False` prints the sign and colours `[`, `/x`, `42` and `True`; adding `emoji=False, highlight=False` prints the text literally, and a `style="red"` line stays uniformly red | **Fixed**: the three prints also pass `emoji=False, highlight=False` (17.1). Tests 10 to 13 print text holding `:warning: 42 True` on a terminal console (17.2) |
| R1-2: D1 claimed a non-dict `params` is "read as absent" | P3, injected-only, not a regression | The real base `perceive` raises first (`cognitive_agent.py:3100`, `AttributeError: 'NoneType' object has no attribute 'get'`) | **Sentence deleted** (D1). The `isinstance(params, dict)` guard stays; no claim rests on it |

Rejected: `Text(...)` objects for the prints, because it makes the tracker sentences "with `markup=False`" false, which means two tracker pairs and a ledger regeneration. A helper, because it adds a name for three calls and one mutant would cover all three prints. A `**` keyword dict, because it is less readable. The per-print form follows `src/probos/__main__.py:3039` and `:3048` (`markup=False, emoji=False`).

Sections 2, 3 (D1, D3), 6, 7.1, 7.3, 10, 12, 13 and 14, and the header, were corrected in place. The blocks below move the files as committed at `5ee64550` to the state those sections now show. Where an older sentence disagrees with this section, this section governs. No tracker or ledger text changes: `PROGRESS.md` and `DECISIONS.md` say the handler prints foreign text "with `markup=False`", which stays true.

**Milestone M3** (one Builder delegation, tier LOW): 17.1, then 17.2. Focused gate: section 4's command. Commits: this contract alone, then the source and the test.

### 17.1 `src/probos/experience/commands/commands_diagnostic.py` (A1, pairs A1-1 to A1-3; 125 to 127 lines)

**A1-1.** SEARCH (once, `:96-100` of the committed file):
```python
            console.print(
                f"Diagnostic failed: {intent_result.error or 'no error given'}",
                style="red",
                markup=False,
            )
```
REPLACE:
```python
            console.print(
                f"Diagnostic failed: {intent_result.error or 'no error given'}",
                style="red",
                markup=False,
                emoji=False,
                highlight=False,
            )
```

**A1-2.** SEARCH (once, `:108-110` of the committed file):
```python
            # The LLM's own words, shown as text: never parsed as Rich markup.
            console.print("The Diagnostician's reply is not a JSON diagnosis:", style="yellow")
            console.print(unparsed, markup=False)
```
REPLACE:
```python
            # The LLM's own words, shown as received: no markup, emoji codes or highlighting.
            console.print("The Diagnostician's reply is not a JSON diagnosis:", style="yellow")
            console.print(unparsed, markup=False, emoji=False, highlight=False)
```

**A1-3.** SEARCH (once, `:124-125` of the committed file):
```python
        # BF-991: the error text is foreign text; as markup, a "[/x]" in it raises again here.
        console.print(f"Diagnostic error: {e}", style="red", markup=False)
```
REPLACE:
```python
        # BF-991: the error text is foreign text, printed as received; as markup, a "[/x]" in it raises again here.
        console.print(f"Diagnostic error: {e}", style="red", markup=False, emoji=False, highlight=False)
```

### 17.2 `tests/test_bf991_diagnostic_intent_message.py` (A1, pairs A1-4 to A1-9; 244 to 259 lines)

**A1-4.** SEARCH (once, `:31-32` of the committed file):
```python
_MARKER = "W-1840"
_FOCUS = "focus-bf991"
```
REPLACE:
```python
_MARKER = "W-1840"
_FOCUS = "focus-bf991"
# Text Rich rewrites unless told not to: an emoji code, and a number and a boolean it highlights on a terminal.
_LITERAL = ":warning: 42 True"
```

**A1-5.** SEARCH (once, `:93-98` of the committed file):
```python
def _shell(agent: Any) -> tuple[SimpleNamespace, Console, StringIO]:
    """The ship as the handler reads it: one healthy agent in the ``medical_diagnostician`` pool."""
    pool = SimpleNamespace(healthy_agents=[agent.id], registry=SimpleNamespace(get=lambda _agent_id: agent))
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    return SimpleNamespace(pools={"medical_diagnostician": pool}), console, buf
```
REPLACE:
```python
def _shell(agent: Any, *, terminal: bool = False) -> tuple[SimpleNamespace, Console, StringIO]:
    """The ship as the handler reads it: one healthy agent in the ``medical_diagnostician`` pool.

    ``terminal=True`` gives a console that writes ANSI codes whatever the environment says,
    so Rich's styles, and any highlighting, show in the buffer.
    """
    pool = SimpleNamespace(healthy_agents=[agent.id], registry=SimpleNamespace(get=lambda _agent_id: agent))
    buf = StringIO()
    if terminal:
        console = Console(
            file=buf, force_terminal=True, color_system="standard", legacy_windows=False, no_color=False, width=120
        )
    else:
        console = Console(file=buf, force_terminal=False, width=120)
    return SimpleNamespace(pools={"medical_diagnostician": pool}), console, buf
```

**A1-6.** SEARCH (once, `:196-212` of the committed file):
```python
@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        ("Ship nominal [x] no JSON here", "Ship nominal [x] no JSON here"),
        ("```json\n[1, 2]\n```", "[1, 2]"),
    ],
    ids=["text-with-brackets", "fenced-json-array"],
)
async def test_a_reply_that_is_not_a_diagnosis_is_printed_as_text(reply: str, shown: str) -> None:
    agent, llm, _ = _agent(reply)
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "Diagnostic L3" in out, out
    assert shown in out, out
    assert llm.complete.await_count == 1
```
REPLACE:
```python
@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        (f"Ship nominal [x] {_LITERAL} no JSON here", f"Ship nominal [x] {_LITERAL} no JSON here"),
        ("```json\n[1, 2]\n```", "[1, 2]"),
    ],
    ids=["text-with-brackets", "fenced-json-array"],
)
async def test_a_reply_that_is_not_a_diagnosis_is_printed_as_text(reply: str, shown: str) -> None:
    agent, llm, _ = _agent(reply)
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "Root cause" in out, out
    assert shown in out, out
    assert llm.complete.await_count == 1
```

**A1-7.** SEARCH (once, `:215-222` of the committed file):
```python
async def test_a_failed_result_prints_its_error_and_no_panel() -> None:
    failed = IntentResult(intent_id="i-bf991", agent_id="diag-bf991", success=False, error="boom [/x]")
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(return_value=failed))
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic failed: boom [/x]" in out, out
    assert "Root cause" not in out, out
```
REPLACE:
```python
async def test_a_failed_result_prints_its_error_and_no_panel() -> None:
    failed = IntentResult(
        intent_id="i-bf991", agent_id="diag-bf991", success=False, error=f"boom [/x] {_LITERAL}"
    )
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(return_value=failed))
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert f"Diagnostic failed: boom [/x] {_LITERAL}" in out, out
    assert "Root cause" not in out, out
```

**A1-8.** SEARCH (once, `:225-236` of the committed file):
```python
async def test_llm_text_in_the_panel_is_shown_as_text_not_markup() -> None:
    reply = (
        '{"severity": "low", "category": "agent", "root_cause": "[/x] stray tag", '
        '"evidence": ["pool [core] low"], "recommended_treatment": "none"}'
    )
    agent, _, _ = _agent(reply)
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "[/x] stray tag" in out, out
    assert "[core]" in out, out
```
REPLACE:
```python
async def test_llm_text_in_the_panel_is_shown_as_text_not_markup() -> None:
    reply = (
        '{"severity": "low", "category": "agent", "root_cause": "[/x] '
        + _LITERAL
        + ' stray tag", "evidence": ["pool [core] low"], "recommended_treatment": "none"}'
    )
    agent, _, _ = _agent(reply)
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert f"[/x] {_LITERAL} stray tag" in out, out
    assert "[core]" in out, out
```

**A1-9.** SEARCH (once, `:239-244` of the committed file):
```python
async def test_an_error_text_that_looks_like_markup_is_printed_not_raised() -> None:
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(side_effect=RuntimeError("bad [/x] tag")))
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error: bad [/x] tag" in out, out
```
REPLACE:
```python
async def test_an_error_text_that_looks_like_markup_is_printed_not_raised() -> None:
    error = RuntimeError(f"bad [/x] {_LITERAL} tag")
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(side_effect=error))
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert f"Diagnostic error: bad [/x] {_LITERAL} tag" in out, out
```

### 17.3 Predicted red and green

- With only 17.2 on the `5ee64550` tree: 10[text-with-brackets], 10[fenced-json-array], 11 and 13 red, because the sign or the highlight codes break the expected substring. The other 10 cases, test 12 included, are green: `Text` cells already print literally, so test 12 kills nothing new and measures the claim of property 3.
- After 17.1: 14 green. Section 4's gate: 58 passed.

### 17.4 Mutation rows (A1)

Rerun the whole campaign on the final files: the rows of section 10 and the six rows M11a to M13b, each killed by exactly its listed tests. Record the sha256 of the LF text of `commands_diagnostic.py` and of the test file.

### 17.5 Review round 2: properties to verify

1. The delta changes only the two files plus this contract; no tracker or ledger file changes.
2. Each of the three prints of foreign text carries `markup=False, emoji=False, highlight=False`, and each new kwarg has a row of 17.4 with a killer.
3. Tests 10 to 13 assert the foreign text unbroken on a terminal console; tests 8 and 9 are unchanged in effect.
4. The deleted D1 sentence is not restated anywhere.
5. The claims of the amended sections are true of the files: the header's sentence about the BF number in a SEARCH names A1-3; sections 2, 3, 6, 7.1, 7.3, 10, 12, 13, 14 and 17 agree on which prints carry which keyword arguments and which tests pin them; the case count stays 14.

### 17.6 The orchestrator's first-hand checks (2026-11-20, the oracle tree at `3331b4ac` with the M1 files, before the Builder started)

| P | Check | Result |
|---|---|---|
| P1 | The nine SEARCH blocks against the files of `5ee64550` (`audit\build_a1_pairs_b991.py`, `audit\a1_tools_b991.py`) | Each occurs exactly once at its turn, and the files end at 127 lines (`commands_diagnostic.py`) and 259 lines (the test file), as 17.1 and 17.2 state |
| P2 | 17.2 alone on the M1 files, the new file at `-n 0` | 4 failed, 10 passed, as 17.3 predicts: 10[text-with-brackets], 10[fenced-json-array], 11 and 13 fail. Test 13's output shows the sign (`\u26a0`) in place of `:warning:` and colour codes around `[`, `/`, `x`, `]`, `42` and `True` |
| P3 | 17.1 on top, then the focused gate of section 4 | All 14 new cases green; 58 passed (14 new, 44 in the three existing files). `Root cause` is unbroken in the terminal output, so the panel marker of test 10 holds |
| P4 | The whole campaign (`audit\mutants_bf991.py`): the 12 rows of section 10, the six rows of 17.4, and three evidence rows X1 to X3 (the `markup=False` of each print dropped one at a time) | All 21 rows killed, each by exactly its listed tests and no other case. M12a is killed by 10[text-with-brackets] alone and M12b by both cases of test 10. X1, X2 and X3 are killed by test 11, 10[text-with-brackets] and 13 |
| P5 | The files after A1, the base of the record (sha256 is of the LF text; section 16's values are of the oracle's files as they lay on disk, CRLF for the source files and LF for the test file) | `commands_diagnostic.py`: blob `ff93e01767fa2dc5ed8c30f5b9bd582a29cfb043`, sha256 `bd89aa964032a9b34a32c5d7ceceecf625c0f99d0e522ea67ec85946a7c90c52`. The test file: blob `169af6abec4cbf87937f1ffce23e209994de93a0`, sha256 `916e0bee0e1ffc7e804890c8012e4633fbf46fd25eacea966610f418385d3cf9`. `diagnostician.py` and `panels.py` are unchanged |
| P6 | The consult's pointers into the installed Rich (15.0.0) | `rich/console.py:707-712` (colour system), `:726-728` (`no_color`), `:939-940` (`force_terminal`), `:1437` and `:1453-1454` (emoji), `:1462` (highlighter) hold what the consult says |
| P7 | The same gap in `/scout` (`G:\tmp\r1probe\probe_scout_literal.py`, premises asserted: the control with all three keyword arguments is literal) | Present: see 17.7 |

### 17.7 New item on #1820 (bf-991 F2)

`- [ ] **bf-991 F2 (P3, Low; pre-existing, not a regression of BF-991): /scout prints the Scout's report and its error text with markup=False only, so Rich still turns an emoji code in them into a sign and, on a terminal, colours their numbers, booleans and brackets.**` Evidence: `src/probos/experience/commands/commands_knowledge.py:155` (`console.print(output, markup=False)`) and `:157` (`Scout error: ...`, `markup=False`); the comment at `:154` names BF-935 A2. Rich runs its emoji and highlight passes on a `str` whatever `markup` says (`rich/console.py:1437-1462`). Probe `probe_scout_literal.py` on a terminal console (2026-11-20, premises asserted): a report holding `Report [x] :warning: 42 True end` prints `\u26a0` in place of `:warning:` and wraps `[`, `]`, `42` and `True` in colour codes, and an error holding `boom [/x] :warning: 42 True end` does the same inside the red line. BF-991 amendment A1 repairs the same fault in `/diagnostic`. **Smallest repair:** add `emoji=False, highlight=False` to the two prints and pin each with a terminal-console case, as `tests/test_bf991_diagnostic_intent_message.py` does. `rg -n "markup=False" src/probos --glob "*.py"` (2026-11-20, `5ee64550`) lists nine call sites: the four of `commands_diagnostic.py` (three repaired by A1, the fourth the handler's own text), the two of `/scout`, `src/probos/__main__.py:3039` and `:3048` (both already `emoji=False`), and `:3007` (a refusal that quotes a configured path; the repair should check it). No site in `src/probos` used `highlight=False` before A1. **Nearest neighbour:** #1674 (closed, BF-935) and #1840 (BF-991).
