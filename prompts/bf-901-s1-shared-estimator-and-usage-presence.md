# BF-901 S1: one owner for the token estimator, and usage presence at the transport

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21

**Status:** build-ready. **Part of #1575** (slice S1 of S1 to S3; #1575 stays open until S3). **Tier HIGH** (a shared contract: `LLMResponse`, 53 caller files of `.complete(`; the estimator BF-680 and AD-1142 own). **Base:** `origin/main` `8c8bc4415e6279a22ffe2151cbd6cbc81b993691` **plus BF-900 applied** (`prompts/bf-900-dispatch-claim-keeps-the-park.md`); this contract's source SEARCH blocks touch no file BF-900 edits, and its tracker blocks anchor on BF-900's entries. **Batch:** item 2 of 3; BF-901 S2 (`prompts/bf-901-s2-journal-token-provenance.md`) is applied on top of this one. **Source:** the Architect's consult of 2026-10-21 (13:58Z), re-verified (section 11).

**Tests:** the one statement of the count is section 6: 33 new test cases (16 test functions) in one new file, one existing test changed.

**Line endings:** every edited file's working copy is CRLF (`git ls-files --eol`: `i/lf w/crlf`). The SEARCH blocks are written with LF; match and write with the file's own line endings.

---

## 1. Problem

BF-680 (#1078) found that the Copilot proxy answers every completion with `usage` zeros, and fixed the agentic loop only: a zero beside output is an absent measurement, estimated client-side and labelled (`swe_harness/agentic_loop.py:996` `_completion_is_non_empty`, `:1029` `_estimate_call_tokens`, on AD-1142's `:926` `_estimate_context_tokens`). The one-shot paths (the journal rows #1575 measures) record the proxy's zeros. Two things are missing before S2 can record honestly:

1. **One estimator owner.** The three functions live in the loop module; DD-3 of AD-1142 kept `_estimate_context_tokens` module-local on purpose (`agentic_loop.py:938-940`). A second estimator in the one-shot path would drift from the loop's.
2. **Usage presence.** `_call_openai` reads `usage.get("total_tokens", 0)` and its two siblings (`llm_client.py:2415-2418`); `_call_ollama_native` reads `data.get("prompt_eval_count", 0)` and `data.get("eval_count", 0)` (`:2478-2480`). A reply with no usage block is indistinguishable from one that reports 0; `LLMResponse` has no flag for it (`types.py:334-361`).

## 2. Solution overview

- A new module `probos/cognitive/token_accounting.py` owns the three functions, moved with their bodies unchanged. Two docstring sentences change because they would be false after the move (section 3, D2).
- `agentic_loop` imports the three names **by name at module scope** and keeps calling them unqualified, so the monkeypatches on the loop module (`test_bf680_token_usage_fallback.py:155-156`, `:281`; `test_ad1190_delegation_tree_budget.py:1685`, `:1732`; `test_ad1200_repository_instruction_wire.py:577-585`) still replace what the loop calls. The loop's code is otherwise untouched and never reads the new flag.
- `LLMResponse.usage_reported: bool | None = None`. `_call_openai` sets it from `"total_tokens" in usage`; `_call_ollama_native` from both count keys being present. The counts stay exactly as the provider reported them.
- `charge_completion(outbound, response) -> TokenCharge(prompt_tokens, completion_tokens, total_tokens, source)`: BF-680's rule plus presence (section 3, D5). `request_messages(request)` builds the estimator's view of one `LLMRequest`; `answered_model_name(response)` names the model that answered. S2 calls all three; nothing in S1 calls them outside the tests.

**Not applicable: streamed replies.** ProbOS never streams: `Grep "\"stream\":\s*True|stream=True|stream_options" src/probos/` finds nothing; `"stream": False` appears at the sites listed under Absence Verified (section 11): the Ollama model warm-up in `__main__.py`, and the client's probe and native-chat payloads. #1575's streamed clause is recorded as not applicable (DECISIONS entry).

## 3. Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | The three functions move to `probos/cognitive/token_accounting.py`; `agentic_loop` imports them by name at module scope | A second estimator for the one-shot path (the issue forbids it: one owner). Importing the module and calling `token_accounting._estimate_call_tokens(...)` from the loop: the five monkeypatch seams on the loop module would stop working |
| D2 | **DD-3 override, stated:** AD-1142's DD-3 kept `_estimate_context_tokens` module-local "rather than imported from `session_compactor`" so the loop takes no dependency on the compactor. The move keeps that reason (the new module does not import the compactor) and drops "module-local", because one owner now serves the loop and the journal paths. The docstring says so; `_completion_is_non_empty`'s first sentence ("`LLMResponse` carries no 'usage was present' flag") is rewritten to say the loop reads none | Keeping the docstrings verbatim: two sentences would be false. Moving into `swe_harness/`: the owner serves non-harness callers (S2) |
| D3 | `usage_reported: bool | None = None`, a trailing defaulted field. `True`: the transport found the usage keys (OpenAI format: `total_tokens` in `usage`; Ollama native: both count keys). `False`: it did not, which can sit beside a nonzero partial count (`eval_count` alone). `None`: not stated (test doubles, the mock client, cache replays, errors) | A `bool` defaulting to `False`: every double that sets `tokens_used=42` (for example `test_ad632e_evaluate_reflect.py:285-288`) would be charged as an estimate in S2. Defaulting to `True`: claims presence for objects that never parsed a reply |
| D4 | The counts on `LLMResponse` are unchanged; only the flag is added | Rewriting a missing count to an estimate in the transport: changes what the agentic loop reads (byte-identity) and what 53 caller files see |
| D5 | `charge_completion` rule: an error response, or no output with usage absent: nothing to account for (`source ""`, zeros). Otherwise usage not absent (`True` or `None`) and not "zero beside output": **measured**, the counts as reported when each is a non-negative exact `int` (any other count reads as 0, D6's exact-type reading). Otherwise output: **estimated** (`_estimate_context_tokens(outbound)` for the prompt, `_estimate_call_tokens(outbound, response)` for the total, the difference for the completion). Remaining case (usage reported, total 0, no output): measured 0 | Labelling a no-output, no-usage call `measured 0`: it was not measured. Estimating when the provider reported counts: discards a measurement |
| D6 | `charge_completion` reads the response with `getattr` and exact-type checks (`type(x) is int`, `type(x) is bool`, `type(x) is str`) and treats a response without `content_blocks` as having no output | Attribute access only: the four sub-task handlers' doubles include `MagicMock` responses (`test_ad632d_compose_handler.py:58-62`) and S2's charge must not turn a double into a handler failure. The loop's own charge reads the same way (`agentic_loop.py:889`, `:914`) |
| D7 | `answered_model_name`: AD-1327's `answered_model` when it is a non-blank string, else `model`, else `"unknown"` | `model` alone: that is the id sent, and #1575 asks for the model that answered (`types.py:355-361`) |
| D8 | The loop does not read `usage_reported` | Letting it: the loop's arithmetic and labels would change for a provider that omits usage, and BF-680's tests and AD-1152's golden observation pin them |

## 4. Milestones (about 45 Builder tool calls in all)

| M | Work | Focused check (`-n 0`, the orchestrator's worktree environment: `PYTHONPATH=<tree>/src`) |
|---|---|---|
| M1 (about 8 calls) | Section 7.1 (new module) and 7.2 (`agentic_loop.py`) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf680_token_usage_fallback.py tests/test_ad1142_crew_child_compaction.py tests/test_ad1190_delegation_tree_budget.py tests/test_ad1200_repository_instruction_wire.py tests/test_ad1152_agentic_correlation.py tests/test_ad1324_srp_layout.py tests/test_ad1320_agentic_budget_awareness.py -n 0 -q` |
| M2 (about 6 calls) | Sections 7.3 (`types.py`), 7.4 (`llm_client.py`) and 7.5 (`test_ad1325_boundaries.py`) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_llm_client.py tests/test_ad1325_boundaries.py tests/test_ad543_tool_call_protocol.py tests/test_ad835_tier_adaptation.py tests/test_ad734_wire_shape_contract.py tests/test_ad1327_verifier_tier.py -n 0 -q` |
| M3 (about 18 calls) | Section 7.6 (the new test file) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf901_s1_token_accounting.py -n 0 -q`, then M1's and M2's commands again, then `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1208_cost_bounded_turns.py tests/test_ad1343_seam_registry.py tests/test_layer_boundaries.py -n 0 -q` |
| M4 (about 7 calls) | Section 8: `PROGRESS.md`, `DECISIONS.md`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` | `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -n 0 -q` |
| M5 (about 4 calls) | Section audit; stage by explicit path: `src/probos/cognitive/token_accounting.py`, `src/probos/cognitive/swe_harness/agentic_loop.py`, `src/probos/types.py`, `src/probos/cognitive/llm_client.py`, `tests/test_ad1325_boundaries.py`, `tests/test_bf901_s1_token_accounting.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` (never `git add -A`) | `git diff --cached --stat` |

Then the orchestrator: the scratch-tree dry run (on the tree with BF-900 applied), the golden test on the base (section 6, G1), the mutation rows (section 10), review, the local commit, then S2.

## 5. Consumers of every value this changes

Greps: `Grep "_estimate_call_tokens|_completion_is_non_empty|_estimate_context_tokens" src/ tests/`; `Grep "fields\(LLMResponse|LLMResponse\.__dataclass_fields__|asdict\(resp|asdict\(response|usage_reported" --glob "*.py"` (repository); `Grep "tokens_used=\w+\.tokens_used" src/probos/`; `Grep "answered_tier=|replace\(response|replace\(resp" src/probos/cognitive/llm_client.py`.

| Value | Consumer | What it does with the new value | Base or added |
|---|---|---|---|
| The three estimator names | `agentic_loop.py` :892-893, :915-916, :980, :1476, :1494, :1785, :2113, :2430 (module-global calls) | The same functions, now bound by import; behaviour identical | Added (the move) |
| | Tests importing them from the loop: `test_bf680_token_usage_fallback.py:35-44`, `test_ad1142_crew_child_compaction.py:54-59` | The names still exist on the loop module | Unchanged |
| | Monkeypatches on the loop module: `test_bf680...:155-156`, `:281`; `test_ad1190...:1685`, `:1732`; `test_ad1200...:577-585` | They replace the loop module's global, which is what the loop calls. `_estimate_call_tokens` calls `_estimate_context_tokens` inside the new module, so patching the latter on the loop module would not reach the former; no test does that (the grep above: `_estimate_context_tokens` is never monkeypatched) | Unchanged |
| | Docstring pins: `test_ad1142...:1302-1303`, `:1320-1325` (no banned transparency claim), `:1328-1337` (every "transparency" line negated), `:1367-1372` (`ad-547b`, `does not discharge`) | The amended docstring keeps `AD-547b` and "does NOT discharge" and adds no banned phrase and no "transparency" | Unchanged |
| `LLMResponse.usage_reported` | `_call_openai`, `_call_ollama_native` (set it) | Section 7.4 | Added |
| | `OpenAICompatibleClient.complete` attempt loop: `response = replace(response, answered_tier=attempt_tier)` (`llm_client.py:1833`) | `dataclasses.replace` keeps the flag | Unchanged |
| | Cache replays (`llm_client.py:1526-1530`, `:2001-2010`) and error responses (`:1531-1535`, `:2020-2096`) build a new `LLMResponse` without it | `None`; S2 records replays as `cached=1` (not counted) and errors as `source ""` | Unchanged here |
| | `asdict(response)` in `tests/test_ad1325_boundaries.py:229-232` (a byte-exact base fixture) | Would gain a key; section 7.5 excludes it, as AD-1327 did | Changed (pinned default in this contract's D1 test) |
| | Every other reader of `LLMResponse` (53 caller files of `.complete(`) | A trailing defaulted field: keyword and positional construction unchanged; no `==` comparison of whole responses in tests (`Grep "== LLMResponse\(" tests/` finds nothing) | Unchanged |
| | The agentic loop | Never reads it (D8; test X3) | Unchanged |
| `charge_completion`, `TokenCharge`, `request_messages`, `answered_model_name` | Nothing in `src/` in S1 (`Grep "charge_completion|request_messages|answered_model_name" src/probos/` finds only the new module); S2's journal sites | — | Added |

Pre-existing on the base and not repaired here: `MockLLMClient` sets `tokens_used=len(content)//4` (`llm_client.py:2913-3060`) with no presence (S2 records those counts as measured under the `None` rule; they carry `model="mock"`); considered, deferred (section 9).

## 6. Tests

All in `tests/test_bf901_s1_token_accounting.py` unless named.

| ID | Test | What it proves |
|---|---|---|
| P1 | `test_openai_reply_with_usage_is_reported_and_measured` | Fake provider, usage present: counts 100/50/150, `usage_reported is True`, charge measured |
| P2 | `test_openai_reply_without_a_usage_block_is_not_reported_and_is_estimated` | No `usage` key: counts 0, `usage_reported is False`, charge estimated |
| P3 | `test_openai_zeros_beside_content_are_reported_but_charged_as_an_estimate` | The proxy's shape: `usage_reported is True`, counts 0, charge estimated (BF-680's rule) |
| P4 | `test_openai_tool_call_only_reply_with_zeros_is_charged_as_an_estimate` | A tool call with no text counts as output |
| P5 | `test_ollama_reply_with_counts_is_reported_and_measured` | 10/5/15, `True`, measured |
| P6 | `test_ollama_reply_missing_prompt_eval_count_is_not_reported_and_is_estimated` | Counts as reported today (0/5/5), `False`, charge estimated |
| C1 | `test_charge_follows_the_rule[...]`, 11 ids: `measured`, `proxy_zeros`, `absent_with_output`, `absent_no_output`, `reported_zero_no_output`, `error`, `unstated_counts`, `unstated_zero_output`, `unstated_zero_no_output`, `double_without_blocks`, `mock_double` | D5 and D6, each row's exact `(prompt, completion, total, source)` |
| C2 | `test_an_estimate_splits_prompt_and_completion` | `prompt == 100`, `completion == 20`, `total == 120` for a 400-character prompt and an 80-character reply |
| G1 | `test_the_moved_functions_return_the_base_integers` | Golden: fixed inputs give 100, 101, 5, 119, 120 and the four non-empty verdicts. Imports the functions from the **loop module**, so the orchestrator runs this one test on the base tree too (where it must pass unchanged) |
| G2 | `test_the_loop_calls_the_shared_functions` | Identity: `agentic_loop._estimate_call_tokens is token_accounting._estimate_call_tokens`, and the other two |
| R1 | `test_request_messages_mirrors_the_wire_composition[...]`, 4 ids | prompt with and without a system prompt; `messages` with and without a leading system message |
| A1 | `test_answered_model_name[...]`, 5 ids | answered, sent, and `"unknown"` for blank, `None` and `MagicMock` names |
| X1 | `test_an_estimated_loop_outcome_reaches_the_cost_stop_wording` | Cross-seam: a real `AgenticLoop` over zero-usage turns stops at its budget with `token_source == "estimated"`; `TurnCostBudget.record` then `render_stop` carries " (usage estimated, not measured)" (`turn_cost.py:79`, `:269-271`) |
| X2 | `test_a_measured_loop_outcome_keeps_the_plain_wording` | The control: reported counts, no "estimated" in the stop text |
| X3 | `test_the_loop_ignores_usage_reported` | Responses with counts and `usage_reported=False` are charged by the loop as measured, summed exactly (D8) |
| D1 | `test_usage_reported_defaults_to_none` | The default the AD-1325 fixture exclusion relies on |
| E1 | `tests/test_ad1325_boundaries.py::test_flag_off_public_observation_matches_required_base_fixture_bytes` (changed) | The base fixture stays byte-exact with the new key excluded, as AD-1327's were |

Consumer tests run unchanged (M1 to M3): `test_bf680_token_usage_fallback.py`, `test_ad1142_crew_child_compaction.py`, `test_ad1190_delegation_tree_budget.py`, `test_ad1200_repository_instruction_wire.py`, `test_ad1152_agentic_correlation.py` (AD-1152's golden observation of the loop: `token_source`, `total_tokens`, the events), `test_ad1208_cost_bounded_turns.py`, `test_llm_client.py`, `test_ad543_tool_call_protocol.py`, `test_ad835_tier_adaptation.py`, `test_ad734_wire_shape_contract.py`, `test_ad1327_verifier_tier.py`, `test_ad1324_srp_layout.py`, `test_ad1320_agentic_budget_awareness.py`, `test_ad1343_seam_registry.py`, `test_layer_boundaries.py`.

**Platform.** No test touches the file system, a process or the clock beyond the loop's own `time` reads; the fake provider is an in-memory `httpx.Response`. The outcome cannot differ on POSIX.

## 7. The contract

### 7.1 New file

#### `src/probos/cognitive/token_accounting.py`

```python
"""BF-901 (#1575): one owner for what a model call is charged, measured or estimated.

BF-680 built the estimator inside the agentic loop for the paths that loop runs. This module owns it now,
so the one-shot paths (the journal rows ``cognitive_agent`` and the sub-task chain write, BF-901 S2) charge
with the same estimate instead of a second one. ``_completion_is_non_empty``, ``_estimate_call_tokens`` and
AD-1142's ``_estimate_context_tokens`` were moved here from ``swe_harness/agentic_loop.py`` with their bodies
unchanged; the loop imports them by name and calls them unqualified, so a monkeypatch on the loop module
still replaces what the loop calls.

``charge_completion`` adds what the loop does not read: whether the provider's reply carried its usage counts
(``LLMResponse.usage_reported``, set by ``OpenAICompatibleClient._call_openai`` and ``_call_ollama_native``).
The loop never reads that flag, which keeps its arithmetic and labels as BF-680 left them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from probos.cognitive.swe_harness.tool_call import TextBlock, ToolUseBlock
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED

#: ``TokenCharge.source`` when there is nothing to account for: an error, or neither output nor reported
#: usage. Never counted as measured.
TOKEN_SOURCE_NONE = ""


def _estimate_context_tokens(messages: list[dict]) -> int:
    """AD-1142 / DD-3: approximate the tokens currently OCCUPYING the context.

    Same ``len(text) // 4`` approximation as
    ``session_compactor.estimate_tokens`` — AD-547b still owns the exact
    tokenizer and this AD does NOT discharge its forcing function (the first
    compaction false-trip whose len/4 estimate diverges >25% from real model
    context counting) — but this one ALSO counts the serialised ``tool_calls``
    payload an AD-1146 assistant turn carries. ``estimate_messages_tokens``
    reads ``content`` only, which undercounts a structured history by the whole
    tool-call array.

    Deliberately not imported from ``session_compactor``: the loop has no
    dependency on that module (the compactor arrives injected as ``Any``), and
    DD-3 keeps it that way. BF-901 moved this function out of the loop module
    into ``probos.cognitive.token_accounting``, its one owner, so the one-shot
    journal paths charge with the same estimate; DD-3's reason still holds,
    because this module does not import the compactor either.

    Non-dict entries are skipped rather than raising. The compactor is an
    injected ``Any``, so what comes back from it is a module boundary, and this
    function is called from the loop's hot path OUTSIDE the ``try`` that
    absorbs compaction failures — a raise here would escape ``run()``, which
    promises never to raise.
    """
    total = 0
    for message in messages:
        if type(message) is not dict:
            continue
        text = str(message.get("content", "") or "")
        tool_calls = message.get("tool_calls")
        if tool_calls:
            try:
                text += json.dumps(
                    tool_calls, separators=(",", ":"), default=str
                )
            except Exception:
                text += str(tool_calls)
        total += max(1, len(text) // 4)
    return total


def _completion_is_non_empty(response: Any) -> bool:
    """BF-680: did this completion actually produce output?

    The agentic loop reads no "usage was present" flag (BF-901's
    ``LLMResponse.usage_reported`` is read by :func:`charge_completion` only),
    so for the loop ``tokens_used`` collapses BOTH "the provider reported 0"
    and "the provider reported nothing" onto the same ``0``. The two are
    therefore indistinguishable at this boundary, and the disambiguation rule
    is stated HERE rather than left to fall out of the arithmetic:

        **A zero that accompanies a completion which produced output is an
        ABSENT measurement, not a measurement of zero.**

    No provider emits text or a tool call for free, so the pairing is only
    reachable when the field was never populated. The live Copilot proxy at
    ``127.0.0.1:8080`` is exactly this case: HTTP 200, real content,
    ``usage.total_tokens == 0``.

    "Produced output" deliberately includes a tool-call-only turn. Those carry
    no text, but they are the turns the agentic loop exists for, so scoring
    them as empty would leave the budget inert on precisely the path it is
    meant to bound.

    A completion with neither text nor tool calls is left alone: its reported
    zero is plausible, and substituting an estimate there would invent spend
    for a turn that produced nothing.
    """
    blocks = list(response.content_blocks or [])
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        return True
    text = "".join(b.text for b in blocks if isinstance(b, TextBlock))
    return bool((text or response.content or "").strip())


def _estimate_call_tokens(outbound: list[dict], response: Any) -> int:
    """BF-680: client-side stand-in for one call's ``prompt + completion`` usage.

    Reuses the AD-1142 estimator on both halves rather than taking a tokenizer
    dependency: ``outbound`` is the history the request was assembled from, and
    the completion is measured through the same pseudo-message shape so a
    tool-calling turn's serialised arguments are counted too.

    Summing this per iteration mirrors how a provider bills an uncached
    multi-turn loop — every turn re-sends the whole history — so the running
    total stays structurally faithful even though each term is approximate.

    Its inaccuracy (``len(text) // 4``; AD-547b still owns the exact tokenizer,
    and this does NOT discharge its forcing function) is acceptable for a
    budget STOP, which only has to fire in the right order of magnitude. It is
    NOT acceptable as billing, which is why every substitution is labelled.
    """
    blocks = list(response.content_blocks or [])
    text = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
    completion = {
        "content": text or response.content or "",
        # Plain dicts rather than the AD-1146 wire shape: this is a size
        # estimate, not a message, and ``_estimate_context_tokens`` already
        # serialises ``tool_calls`` defensively.
        "tool_calls": [
            {
                "id": b.tool_call.id,
                "name": b.tool_call.name,
                "arguments": b.tool_call.arguments,
            }
            for b in blocks
            if isinstance(b, ToolUseBlock)
        ],
    }
    return _estimate_context_tokens(outbound) + _estimate_context_tokens(
        [completion]
    )


@dataclass(frozen=True)
class TokenCharge:
    """BF-901: what one model call is charged, and where the counts came from."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    source: str = TOKEN_SOURCE_NONE  # "measured" | "estimated" | "" (nothing to account for)


def _count(value: object) -> int:
    """A reported count as an ``int``; anything else (a test double's mock, a negative) reads as 0."""
    if type(value) is int and value >= 0:
        return value
    return 0


def charge_completion(outbound: list[dict], response: Any) -> TokenCharge:
    """BF-901: charge one completion, measured when the provider measured it, else estimated.

    ``outbound`` is the history the request was built from (:func:`request_messages` for an ``LLMRequest``).
    The rule, in order:

    * an error response (``error`` a non-empty string) carries no reply: nothing to account for;
    * ``usage_reported`` not ``False`` (``True``, or ``None`` = not stated) and not BF-680's "zero beside
      output": **measured**, the counts as the provider reported them, each read through ``_count`` (a
      count that is not a non-negative exact ``int``, such as ``-7`` or ``5.5``, is charged as 0);
    * no output (and usage absent): nothing to account for (``source ""``, never read as measured);
    * otherwise **estimated**: the prompt is ``_estimate_context_tokens(outbound)``, the total
      ``_estimate_call_tokens(outbound, response)``, the completion their difference.

    The response is read with ``getattr`` and exact types because callers pass whatever their client returns,
    test doubles included; one without ``content_blocks`` is read as having produced no output, so its
    reported counts stand.
    """
    error = getattr(response, "error", None)
    if type(error) is str and error:
        return TokenCharge()
    flag = getattr(response, "usage_reported", None)
    reported = flag if type(flag) is bool else None
    total = _count(getattr(response, "tokens_used", 0))
    try:
        produced = _completion_is_non_empty(response)
    except AttributeError:
        produced = False
    if reported is not False and not (total == 0 and produced):
        return TokenCharge(
            prompt_tokens=_count(getattr(response, "prompt_tokens", 0)),
            completion_tokens=_count(getattr(response, "completion_tokens", 0)),
            total_tokens=total,
            source=TOKEN_SOURCE_MEASURED,
        )
    if not produced:
        return TokenCharge()
    prompt = _estimate_context_tokens(outbound)
    estimate = _estimate_call_tokens(outbound, response)
    return TokenCharge(
        prompt_tokens=prompt,
        completion_tokens=estimate - prompt,
        total_tokens=estimate,
        source=TOKEN_SOURCE_ESTIMATED,
    )


def request_messages(request: Any) -> list[dict]:
    """BF-901: the outbound history of one ``LLMRequest``, in the shape the estimator reads.

    Mirrors how ``OpenAICompatibleClient._call_openai`` composes the messages it posts: ``request.messages``
    when set, with the system prompt first unless a system message leads; otherwise system, then user. The
    attachment resolution and the per-tier system suffix it adds are not counted: this feeds an estimate.
    """
    if request.messages is not None:
        messages = list(request.messages)
        first = messages[0] if messages else None
        if request.system_prompt and not (type(first) is dict and first.get("role") == "system"):
            messages.insert(0, {"role": "system", "content": request.system_prompt})
        return messages
    composed: list[dict] = []
    if request.system_prompt:
        composed.append({"role": "system", "content": request.system_prompt})
    composed.append({"role": "user", "content": request.prompt})
    return composed


def answered_model_name(response: Any) -> str:
    """BF-901: the model that answered (AD-1327's ``answered_model``), else the id sent, else ``"unknown"``.

    Never empty, so a journal row names a model or says it cannot.
    """
    for name in (getattr(response, "answered_model", None), getattr(response, "model", None)):
        if type(name) is str and name.strip():
            return name
    return "unknown"
```

**Import cycle (the consult's risk).** This module imports `probos.cognitive.swe_harness.tool_call` at module scope, as the loop does (`agentic_loop.py:22-33`). The only module-scope importer in S1 is `agentic_loop`, which has imported `tool_call` (line 22) before it reaches the new import, so the new edge adds no cycle: if `tool_call`'s import closure reached `agentic_loop`, the loop's own line-22 import would already fail today. S2 imports this module at the call sites (inside the functions), not at module scope, so it adds no module-scope edge to `cognitive_agent.py` or the sub-task handlers, which import no `swe_harness` module at module scope today (`Grep "^from probos\.cognitive\.(swe_harness|agentic_dispatch)" src/probos/cognitive/` lists neither).

### 7.2 `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
    merge_token_sources as _token_source_label,
)
from probos.cognitive.swe_harness.loop_tier_steps import (
```
REPLACE:
```python
    merge_token_sources as _token_source_label,
)
# BF-901 (#1575): the estimator's one owner. Imported BY NAME at module scope and called unqualified below,
# so ``monkeypatch.setattr(agentic_loop, "_estimate_call_tokens", ...)`` still replaces what the loop calls.
from probos.cognitive.token_accounting import (
    _completion_is_non_empty,
    _estimate_call_tokens,
    _estimate_context_tokens,
)
from probos.cognitive.swe_harness.loop_tier_steps import (
```

SEARCH:
```python
def _estimate_context_tokens(messages: list[dict]) -> int:
    """AD-1142 / DD-3: approximate the tokens currently OCCUPYING the context.

    Same ``len(text) // 4`` approximation as
    ``session_compactor.estimate_tokens`` — AD-547b still owns the exact
    tokenizer and this AD does NOT discharge its forcing function (the first
    compaction false-trip whose len/4 estimate diverges >25% from real model
    context counting) — but this one ALSO counts the serialised ``tool_calls``
    payload an AD-1146 assistant turn carries. ``estimate_messages_tokens``
    reads ``content`` only, which undercounts a structured history by the whole
    tool-call array.

    Deliberately module-local rather than imported from ``session_compactor``:
    the loop has no dependency on that module today (the compactor arrives
    injected as ``Any``), and DD-3 keeps it that way.

    Non-dict entries are skipped rather than raising. The compactor is an
    injected ``Any``, so what comes back from it is a module boundary, and this
    function is called from the loop's hot path OUTSIDE the ``try`` that
    absorbs compaction failures — a raise here would escape ``run()``, which
    promises never to raise.
    """
    total = 0
    for message in messages:
        if type(message) is not dict:
            continue
        text = str(message.get("content", "") or "")
        tool_calls = message.get("tool_calls")
        if tool_calls:
            try:
                text += json.dumps(
                    tool_calls, separators=(",", ":"), default=str
                )
            except Exception:
                text += str(tool_calls)
        total += max(1, len(text) // 4)
    return total


def _largest_group_tokens(messages: list[dict]) -> int:
```
REPLACE:
```python
def _largest_group_tokens(messages: list[dict]) -> int:
```

SEARCH:
```python
def _completion_is_non_empty(response: Any) -> bool:
    """BF-680: did this completion actually produce output?

    ``LLMResponse`` carries no "usage was present" flag, so ``tokens_used``
    collapses BOTH "the provider reported 0" and "the provider reported
    nothing" onto the same ``0``. The two are therefore indistinguishable at
    this boundary, and the disambiguation rule is stated HERE rather than left
    to fall out of the arithmetic:

        **A zero that accompanies a completion which produced output is an
        ABSENT measurement, not a measurement of zero.**

    No provider emits text or a tool call for free, so the pairing is only
    reachable when the field was never populated. The live Copilot proxy at
    ``127.0.0.1:8080`` is exactly this case: HTTP 200, real content,
    ``usage.total_tokens == 0``.

    "Produced output" deliberately includes a tool-call-only turn. Those carry
    no text, but they are the turns the agentic loop exists for, so scoring
    them as empty would leave the budget inert on precisely the path it is
    meant to bound.

    A completion with neither text nor tool calls is left alone: its reported
    zero is plausible, and substituting an estimate there would invent spend
    for a turn that produced nothing.
    """
    blocks = list(response.content_blocks or [])
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        return True
    text = "".join(b.text for b in blocks if isinstance(b, TextBlock))
    return bool((text or response.content or "").strip())


def _estimate_call_tokens(outbound: list[dict], response: Any) -> int:
    """BF-680: client-side stand-in for one call's ``prompt + completion`` usage.

    Reuses the AD-1142 estimator on both halves rather than taking a tokenizer
    dependency: ``outbound`` is the history the request was assembled from, and
    the completion is measured through the same pseudo-message shape so a
    tool-calling turn's serialised arguments are counted too.

    Summing this per iteration mirrors how a provider bills an uncached
    multi-turn loop — every turn re-sends the whole history — so the running
    total stays structurally faithful even though each term is approximate.

    Its inaccuracy (``len(text) // 4``; AD-547b still owns the exact tokenizer,
    and this does NOT discharge its forcing function) is acceptable for a
    budget STOP, which only has to fire in the right order of magnitude. It is
    NOT acceptable as billing, which is why every substitution is labelled.
    """
    blocks = list(response.content_blocks or [])
    text = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
    completion = {
        "content": text or response.content or "",
        # Plain dicts rather than the AD-1146 wire shape: this is a size
        # estimate, not a message, and ``_estimate_context_tokens`` already
        # serialises ``tool_calls`` defensively.
        "tool_calls": [
            {
                "id": b.tool_call.id,
                "name": b.tool_call.name,
                "arguments": b.tool_call.arguments,
            }
            for b in blocks
            if isinstance(b, ToolUseBlock)
        ],
    }
    return _estimate_context_tokens(outbound) + _estimate_context_tokens(
        [completion]
    )


@dataclass
class AgenticResult:
```
REPLACE:
```python
@dataclass
class AgenticResult:
```

The loop keeps its own imports: `json`, `TextBlock` and `ToolUseBlock` have other uses in the module (`Grep "\bjson\." src/probos/cognitive/swe_harness/agentic_loop.py` counts 5 before the move, 4 after; `TextBlock` and `ToolUseBlock` are used by the loop body).

### 7.3 `src/probos/types.py`

SEARCH:
```python
    answered_tier: str | None = None
    answered_model: str | None = None


class EscalationTier(Enum):
```
REPLACE:
```python
    answered_tier: str | None = None
    answered_model: str | None = None
    # BF-901: whether the transport found the provider's usage keys; the counts above stay as parsed.
    # True: OpenAI format, ``usage`` has a ``total_tokens`` key (the other two may be absent and read 0);
    # Ollama native, both ``prompt_eval_count`` and ``eval_count`` are present. False: that test failed,
    # which does not make the counts zero (``eval_count`` alone keeps its value beside False). None: not
    # stated (test doubles, the mock client, cache replays, errors). The counts are never rewritten; only
    # ``probos.cognitive.token_accounting.charge_completion`` reads this (the agentic loop does not).
    usage_reported: bool | None = None


class EscalationTier(Enum):
```

### 7.4 `src/probos/cognitive/llm_client.py`

SEARCH:
```python
        usage = data.get("usage", {})
        tokens_used = usage.get("total_tokens", 0)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
            answered_model=_echoed_model(data),
        )
```
REPLACE:
```python
        usage = data.get("usage", {})
        tokens_used = usage.get("total_tokens", 0)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        # BF-901: whether the reply carried a total at all; the counts above stay as reported.
        usage_reported = "total_tokens" in usage

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
            answered_model=_echoed_model(data),
            usage_reported=usage_reported,
        )
```

SEARCH:
```python
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        tokens_used = prompt_tokens + completion_tokens

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
            answered_model=_echoed_model(data),
        )
```
REPLACE:
```python
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        tokens_used = prompt_tokens + completion_tokens
        # BF-901: reported only when both counts are present (Ollama can omit ``prompt_eval_count``, for
        # example on a cached prompt prefix); the counts above stay as reported.
        usage_reported = "prompt_eval_count" in data and "eval_count" in data

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
            answered_model=_echoed_model(data),
            usage_reported=usage_reported,
        )
```

### 7.5 `tests/test_ad1325_boundaries.py`

SEARCH:
```python
        # AD-1327 appended two provenance fields (default None) after this base observation was
        # recorded; the fixture stays the exact base bytes, and test_ad1327_verifier_tier pins the defaults.
        "response": {
            key: value for key, value in asdict(response).items()
            if key not in ("answered_tier", "answered_model")
        },
```
REPLACE:
```python
        # AD-1327 appended two provenance fields (default None) after this base observation was
        # recorded; the fixture stays the exact base bytes, and test_ad1327_verifier_tier pins the defaults.
        # BF-901 appended ``usage_reported`` (default None) the same way; test_bf901_s1_token_accounting
        # pins its default (test_usage_reported_defaults_to_none).
        "response": {
            key: value for key, value in asdict(response).items()
            if key not in ("answered_tier", "answered_model", "usage_reported")
        },
```

### 7.6 New file

#### `tests/test_bf901_s1_token_accounting.py`

```python
"""BF-901 S1 (#1575): one owner for the token estimator, and usage presence at the transport.

The contract is ``prompts/bf-901-s1-shared-estimator-and-usage-presence.md``. Three things are pinned: the
transport records whether the provider reported usage (``LLMResponse.usage_reported``) without changing the
counts; ``charge_completion`` applies BF-680's rule plus that presence; and the agentic loop still calls the
same estimator, now owned by ``probos.cognitive.token_accounting``, with its arithmetic unchanged.

The fake provider is an in-memory ``httpx.Response`` handed to the real ``_call_openai`` / ``_call_ollama_native``
(tests/test_llm_client.py's shape). The loop tests drive a real ``AgenticLoop`` (tests/test_bf680_token_usage_fallback.py's
doubles, copied: tests do not import each other) and a real ``TurnCostBudget``.

Mutants (the contract's section 10): L1 P2; L2 P6; L3 C1[unstated_counts] and D1; TA1 C1[error]; TA2
C1[absent_no_output]; TA3 C1[proxy_zeros]; TA4 C1[absent_no_output]; TA5 C2; TA6 A1[unknown_*]; TA7 and TA8 G1;
TA9 R1[prompt_*].
"""

from __future__ import annotations

from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from probos.cognitive import token_accounting
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.swe_harness import agentic_loop as agentic_loop_module
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.cognitive.token_accounting import (
    TokenCharge,
    answered_model_name,
    charge_completion,
    request_messages,
)
from probos.cognitive.turn_cost import TurnCostBudget
from probos.config import CognitiveConfig
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

OUTBOUND = [{"role": "user", "content": "a" * 400}]  # 400 // 4 = 100 estimated prompt tokens
REPLY = "z" * 80  # 80 // 4 = 20 estimated completion tokens
ESTIMATED_STOP = " (usage estimated, not measured)"  # turn_cost.py:79

# ---------------------------------------------------------------------------
# The fake provider (tests/test_llm_client.py's shape)
# ---------------------------------------------------------------------------


def _httpx_response(status_code: int, *, json: dict) -> httpx.Response:
    resp = httpx.Response(status_code, json=json)
    resp._request = httpx.Request("POST", "http://test")
    return resp


class _Provider:
    """The ``client`` argument of ``_call_openai`` / ``_call_ollama_native``: answers every POST with ``body``."""

    def __init__(self, body: dict) -> None:
        self._body = body
        self.posted: list[tuple[str, dict]] = []

    async def post(self, path: str, *, json: dict, timeout: float) -> httpx.Response:
        self.posted.append((path, json))
        return _httpx_response(200, json=self._body)


def _config() -> CognitiveConfig:
    return CognitiveConfig(
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_api_key="test-key",
        llm_model_fast="qwen3:8b",
        llm_model_standard="claude-sonnet-4",
        llm_model_deep="claude-sonnet-4",
    )


def _openai_body(*, usage: dict | None, content: str | None = "hi", tool_calls: list | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body: dict[str, Any] = {"model": "gpt-x", "choices": [{"message": message, "finish_reason": "stop"}]}
    if usage is not None:
        body["usage"] = usage
    return body


async def _openai(body: dict, request: LLMRequest | None = None) -> LLMResponse:
    client = OpenAICompatibleClient(config=_config())
    try:
        return await client._call_openai(request or LLMRequest(prompt="p", system_prompt="s"), "gpt-x", _Provider(body))
    finally:
        await client.close()


async def _ollama(body: dict) -> LLMResponse:
    client = OpenAICompatibleClient(config=_config())
    try:
        return await client._call_ollama_native(LLMRequest(prompt="p", system_prompt="s"), "qwen3:8b", _Provider(body))
    finally:
        await client.close()


def _charge(response: LLMResponse, request: LLMRequest | None = None) -> TokenCharge:
    return charge_completion(request_messages(request or LLMRequest(prompt="p", system_prompt="s")), response)


# ---------------------------------------------------------------------------
# 1. The transport records presence; the counts stay as reported
# ---------------------------------------------------------------------------


async def test_openai_reply_with_usage_is_reported_and_measured() -> None:
    response = await _openai(_openai_body(usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}))

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (100, 50, 150)
    assert response.usage_reported is True
    assert _charge(response) == TokenCharge(100, 50, 150, TOKEN_SOURCE_MEASURED)


async def test_openai_reply_without_a_usage_block_is_not_reported_and_is_estimated() -> None:
    response = await _openai(_openai_body(usage=None))

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (0, 0, 0)
    assert response.usage_reported is False
    charge = _charge(response)
    assert charge.source == TOKEN_SOURCE_ESTIMATED
    assert charge.total_tokens > 0


async def test_openai_zeros_beside_content_are_reported_but_charged_as_an_estimate() -> None:
    """The live proxy's shape (BF-680): a usage block of zeros and real content."""
    response = await _openai(_openai_body(usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}))

    assert response.usage_reported is True
    assert response.tokens_used == 0
    charge = _charge(response)
    assert charge.source == TOKEN_SOURCE_ESTIMATED
    assert charge.total_tokens > 0


async def test_openai_tool_call_only_reply_with_zeros_is_charged_as_an_estimate() -> None:
    request = LLMRequest(
        prompt="p", system_prompt="s",
        tools=[{"type": "function", "function": {"name": "read_page", "parameters": {"type": "object"}}}],
    )
    body = _openai_body(
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        content=None,
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": "read_page", "arguments": "{}"}}],
    )

    response = await _openai(body, request)

    assert response.content == ""
    assert any(isinstance(b, ToolUseBlock) for b in response.content_blocks)  # premise: a tool call, no text
    assert response.usage_reported is True
    charge = _charge(response, request)
    assert charge.source == TOKEN_SOURCE_ESTIMATED
    assert charge.completion_tokens > 0


async def test_ollama_reply_with_counts_is_reported_and_measured() -> None:
    response = await _ollama(
        {"model": "qwen3:8b", "message": {"role": "assistant", "content": "ok"}, "prompt_eval_count": 10, "eval_count": 5},
    )

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (10, 5, 15)
    assert response.usage_reported is True
    assert _charge(response) == TokenCharge(10, 5, 15, TOKEN_SOURCE_MEASURED)


async def test_ollama_reply_missing_prompt_eval_count_is_not_reported_and_is_estimated() -> None:
    response = await _ollama({"model": "qwen3:8b", "message": {"role": "assistant", "content": "ok"}, "eval_count": 5})

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (0, 5, 5)  # as before
    assert response.usage_reported is False
    assert _charge(response).source == TOKEN_SOURCE_ESTIMATED


# ---------------------------------------------------------------------------
# 2. The charge rule
# ---------------------------------------------------------------------------


def _mock_double() -> Any:
    response = MagicMock()
    response.content = "Test response"
    response.tokens_used = 50
    return response


_RULE_CASES = [
    pytest.param(
        lambda: LLMResponse(content=REPLY, tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True),
        TokenCharge(100, 50, 150, TOKEN_SOURCE_MEASURED), id="measured",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY, usage_reported=True),
        TokenCharge(100, 20, 120, TOKEN_SOURCE_ESTIMATED), id="proxy_zeros",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY, usage_reported=False),
        TokenCharge(100, 20, 120, TOKEN_SOURCE_ESTIMATED), id="absent_with_output",
    ),
    pytest.param(lambda: LLMResponse(content="", usage_reported=False), TokenCharge(0, 0, 0, ""), id="absent_no_output"),
    pytest.param(
        lambda: LLMResponse(content="", usage_reported=True),
        TokenCharge(0, 0, 0, TOKEN_SOURCE_MEASURED), id="reported_zero_no_output",
    ),
    pytest.param(
        lambda: LLMResponse(content="", error="All LLM tiers unavailable"), TokenCharge(0, 0, 0, ""), id="error",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY, tokens_used=150, prompt_tokens=100, completion_tokens=50),
        TokenCharge(100, 50, 150, TOKEN_SOURCE_MEASURED), id="unstated_counts",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY), TokenCharge(100, 20, 120, TOKEN_SOURCE_ESTIMATED), id="unstated_zero_output",
    ),
    pytest.param(
        lambda: LLMResponse(content=""), TokenCharge(0, 0, 0, TOKEN_SOURCE_MEASURED), id="unstated_zero_no_output",
    ),
    pytest.param(
        lambda: SimpleNamespace(content="x", tokens_used=7),
        TokenCharge(0, 0, 7, TOKEN_SOURCE_MEASURED), id="double_without_blocks",
    ),
    pytest.param(_mock_double, TokenCharge(0, 0, 50, TOKEN_SOURCE_MEASURED), id="mock_double"),
]


@pytest.mark.parametrize(("make", "expected"), _RULE_CASES)
def test_charge_follows_the_rule(make: Any, expected: TokenCharge) -> None:
    assert charge_completion(OUTBOUND, make()) == expected


def test_an_estimate_splits_prompt_and_completion() -> None:
    charge = charge_completion(OUTBOUND, LLMResponse(content=REPLY, usage_reported=False))

    assert (charge.prompt_tokens, charge.completion_tokens, charge.total_tokens) == (100, 20, 120)
    assert charge.prompt_tokens + charge.completion_tokens == charge.total_tokens


# ---------------------------------------------------------------------------
# 3. The move: golden integers and identity
# ---------------------------------------------------------------------------


def test_the_moved_functions_return_the_base_integers() -> None:
    """Golden. Read from the loop module, so the same assertions run on the base tree (before the move) and here.
    Each integer is the ``len(text) // 4`` arithmetic of AD-1142 / BF-680 worked by hand in the contract."""
    estimate_context = agentic_loop_module._estimate_context_tokens
    estimate_call = agentic_loop_module._estimate_call_tokens
    non_empty = agentic_loop_module._completion_is_non_empty

    assert estimate_context([{"role": "user", "content": "a" * 400}]) == 100
    assert estimate_context([{"role": "user", "content": "a" * 400}, "skipped", {"role": "assistant", "content": ""}]) == 101
    assert estimate_context([{"role": "assistant", "content": "b" * 8, "tool_calls": [{"id": "c1"}]}]) == 5
    with_tool = LLMResponse(
        content="",
        content_blocks=[TextBlock(text="t" * 40), ToolUseBlock(tool_call=ToolCallRequest(name="n", arguments={}, id="i"))],
    )
    assert estimate_call([{"role": "user", "content": "a" * 400}], with_tool) == 119
    assert estimate_call([{"role": "user", "content": "a" * 400}], LLMResponse(content=REPLY)) == 120
    assert non_empty(LLMResponse(content="x")) is True
    assert non_empty(LLMResponse(content="   ")) is False
    assert non_empty(LLMResponse(content="", content_blocks=[ToolUseBlock()])) is True
    assert non_empty(LLMResponse(content="", content_blocks=[TextBlock(text="  ")])) is False


def test_the_loop_calls_the_shared_functions() -> None:
    for name in ("_completion_is_non_empty", "_estimate_call_tokens", "_estimate_context_tokens"):
        assert getattr(agentic_loop_module, name) is getattr(token_accounting, name), name


# ---------------------------------------------------------------------------
# 4. The helpers S2 uses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        pytest.param(
            LLMRequest(prompt="p", system_prompt="s"),
            [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}], id="prompt_with_system",
        ),
        pytest.param(LLMRequest(prompt="p"), [{"role": "user", "content": "p"}], id="prompt_without_system"),
        pytest.param(
            LLMRequest(prompt="", system_prompt="s", messages=[{"role": "user", "content": "m"}]),
            [{"role": "system", "content": "s"}, {"role": "user", "content": "m"}], id="messages_without_system",
        ),
        pytest.param(
            LLMRequest(prompt="", system_prompt="s", messages=[{"role": "system", "content": "own"}, {"role": "user", "content": "m"}]),
            [{"role": "system", "content": "own"}, {"role": "user", "content": "m"}], id="messages_with_system",
        ),
    ],
)
def test_request_messages_mirrors_the_wire_composition(request_: LLMRequest, expected: list[dict]) -> None:
    assert request_messages(request_) == expected


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        pytest.param(lambda: LLMResponse(content="x", model="sent-id", answered_model="answered-id"), "answered-id", id="answered"),
        pytest.param(lambda: LLMResponse(content="x", model="sent-id"), "sent-id", id="sent"),
        pytest.param(lambda: LLMResponse(content="x", model="", answered_model="  "), "unknown", id="unknown_blank"),
        pytest.param(lambda: SimpleNamespace(content="x"), "unknown", id="unknown_none"),
        pytest.param(MagicMock, "unknown", id="unknown_mock"),
    ],
)
def test_answered_model_name(make: Any, expected: str) -> None:
    assert answered_model_name(make()) == expected


def test_usage_reported_defaults_to_none() -> None:
    assert LLMResponse(content="x").usage_reported is None


# ---------------------------------------------------------------------------
# 5. The loop and the cost stop (tests/test_bf680_token_usage_fallback.py's doubles, copied)
# ---------------------------------------------------------------------------


def _tool_block(call_id: str, *, arg_chars: int = 0) -> ToolUseBlock:
    return ToolUseBlock(
        tool_call=ToolCallRequest(name="read_page", arguments={"url": "https://example.invalid/" + "u" * arg_chars}, id=call_id),
    )


class _ScriptedClient:
    """Replays a fixed list of ``LLMResponse`` objects, then finishes with a text-only turn."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._queue = list(responses)

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        if self._queue:
            return self._queue.pop(0)
        return LLMResponse(content="done", content_blocks=[TextBlock(text="done")])


class _StubExecutor:
    def __init__(self, *, output: str = "ok") -> None:
        self.output = output

    async def invoke(self, *, tool_id: str, **_kwargs: Any) -> ToolResult:
        return ToolResult(output=self.output)


async def _run(responses: list[LLMResponse], **kwargs: Any) -> AgenticResult:
    loop = AgenticLoop(llm_client=_ScriptedClient(responses), tool_executor=_StubExecutor(output="r" * 2000), **kwargs)
    return await loop.run(system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"})


async def test_an_estimated_loop_outcome_reaches_the_cost_stop_wording() -> None:
    """Cross-seam: the shared estimator -> the loop's labelled total -> AD-1208's stop text."""
    turns = [
        LLMResponse(content="w" * 2000, content_blocks=[TextBlock(text="w" * 2000), _tool_block(f"c{i}", arg_chars=200)])
        for i in range(20)
    ]
    result = await _run(turns, max_iterations=10, token_budget=4096)
    assert result.stopped_reason == "token_budget"  # premise: the estimate made the budget fire
    assert result.token_source == TOKEN_SOURCE_ESTIMATED

    budget = TurnCostBudget(budget=4096, max_total_iterations=10)
    budget.record(result)
    text = budget.render_stop("partial work")

    assert ESTIMATED_STOP in text


async def test_a_measured_loop_outcome_keeps_the_plain_wording() -> None:
    turns = [
        LLMResponse(
            content="w", content_blocks=[TextBlock(text="w"), _tool_block(f"c{i}")], tokens_used=5000, usage_reported=True,
        )
        for i in range(3)
    ]
    result = await _run(turns, max_iterations=10, token_budget=4096)
    assert result.stopped_reason == "token_budget"  # premise
    assert result.token_source == TOKEN_SOURCE_MEASURED

    budget = TurnCostBudget(budget=4096, max_total_iterations=10)
    budget.record(result)
    text = budget.render_stop("partial work")

    assert ESTIMATED_STOP not in text
    assert f"{result.total_tokens:,}" in text


async def test_the_loop_ignores_usage_reported() -> None:
    """D8: a reply that says usage was absent but carries counts is charged by the loop exactly as before
    (measured, summed); only ``charge_completion`` reads the flag."""
    turns = [
        LLMResponse(content="ok", content_blocks=[TextBlock(text="ok"), _tool_block("c0")], tokens_used=50, usage_reported=False),
        LLMResponse(content="done", content_blocks=[TextBlock(text="done")], tokens_used=10, usage_reported=False),
    ]

    result = await _run(turns)

    assert result.stopped_reason == "complete"  # premise: two turns, then the text-only turn ended it
    assert result.total_tokens == 60
    assert result.token_source == TOKEN_SOURCE_MEASURED
```

## 8. Tracking (tracker pairs)

**`PROGRESS.md`** (anchored on the first line, the blank line after it and the head of BF-900's entry):

SEARCH:
```markdown
# ProbOS Progress

**BF-900 (2026-10-21), closes #1573 -- the dispatch claim no longer undoes a park made in the same run.**
```
REPLACE:
```markdown
# ProbOS Progress

**BF-901 S1 (2026-10-21), part of #1575 -- one owner for the token estimator, and usage presence at the transport.** BF-680's `_completion_is_non_empty` and `_estimate_call_tokens` and AD-1142's `_estimate_context_tokens` move, bodies unchanged, from `swe_harness/agentic_loop.py` to the new `probos/cognitive/token_accounting.py`; the loop imports them by name and calls them unqualified, so its arithmetic, labels and monkeypatch seams are unchanged (golden and identity tests; AD-1142's DD-3 reason, no dependency on the compactor, still holds). `LLMResponse.usage_reported` (default `None`, not stated) is set by `_call_openai` (`"total_tokens"` present) and `_call_ollama_native` (both count keys present); the counts stay as reported and the loop never reads the flag. `charge_completion(outbound, response)` returns a `TokenCharge` (prompt, completion, total, source): measured when the provider reported usage and BF-680's "zero beside output" does not apply, estimated from the shared estimator when the reply produced output without a usable count, and `""` (nothing to account for) for an error or a reply with neither output nor usage. `request_messages` and `answered_model_name` (the answering model, else the id sent, else `unknown`) serve S2. ProbOS never streams, so #1575's streamed clause does not apply. New: `tests/test_bf901_s1_token_accounting.py`; `tests/test_ad1325_boundaries.py` excludes the new field from its byte-exact base fixture, as AD-1327 did. The decisions are in DECISIONS.md (BF-901 S1); the contract is `prompts/bf-901-s1-shared-estimator-and-usage-presence.md`.

**BF-900 (2026-10-21), closes #1573 -- the dispatch claim no longer undoes a park made in the same run.**
```

**`DECISIONS.md`** (after BF-900's entry, before the heading that follows it):

SEARCH:
```markdown
- *Reversal.* Revert the BF-900 commit. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-900 commit. Nothing persisted changes.

### BF-901 S1 -- One owner for the token estimator, and usage presence at the transport (2026-10-21, part of #1575)

- *Scope.* `probos/cognitive/token_accounting.py` (new), `swe_harness/agentic_loop.py` (the move), `types.py` (`LLMResponse.usage_reported`), `cognitive/llm_client.py` (the two parsers) and tests. Contract: `prompts/bf-901-s1-shared-estimator-and-usage-presence.md` (the Architect's consult of 2026-10-21, 13:58Z). S2 records the charge in the journal; S3 shows it.
- *D1-D2, the DD-3 override.* The three estimator functions move with their bodies unchanged to one owner the journal paths can share; a second estimator would drift from the loop's. AD-1142's DD-3 kept `_estimate_context_tokens` module-local so the loop takes no dependency on `session_compactor`; that reason is kept (the new module does not import the compactor) and "module-local" is dropped, because the loop and the one-shot paths now share it. The loop imports the names at module scope and calls them unqualified, so the monkeypatches on the loop module still replace what it calls.
- *D3-D4.* `usage_reported: bool | None = None`: `True` when the transport found the usage keys (OpenAI format: `total_tokens` in `usage`; Ollama native: both `prompt_eval_count` and `eval_count`), `False` when it did not, `None` not stated (doubles, the mock client, cache replays, errors). The flag records keys, not values: `False` can sit beside a nonzero partial count (`eval_count` alone), and an OpenAI `True` carrying only `total_tokens` reads 0 for the other two. The counts are never rewritten, and the agentic loop never reads the flag, so its totals and labels are as BF-680 left them.
- *D5-D7.* `charge_completion`: an error, or no output with usage absent, is nothing to account for (`source ""`, never read as measured); usage reported or not stated, and not a zero beside output, is measured; otherwise output is estimated (the prompt from the outbound history, the total from `_estimate_call_tokens`, the completion their difference). The response is read with exact types so a test double's mock never becomes a count. `answered_model_name` prefers AD-1327's `answered_model` over the id sent, then `unknown`.
- *Not applicable.* Streamed replies: ProbOS never streams (no `"stream": True`, `stream=True` or `stream_options` in `src/probos`; `"stream": False` is set at all three payloads that carry the key: the Ollama model warm-up in `__main__.py`, and the client's Ollama probe and native-chat payloads).
- *Considered, deferred.* `MockLLMClient`'s `len(content)//4` counts carry no presence, so S2 records them as measured under the not-stated rule; their rows carry `model="mock"`. A journal tap inside the client for the model calls that write no journal row (about 48 files): a design change (it would double-record the existing sites), noted on #1575.
- *Reversal.* Revert the BF-901 S1 commit (and S2 first, which depends on it). Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both belong to the commit. Then `--check` and `tests/test_ad1184_ad_ledger.py` (M4).

**Records the orchestrator adds before the commit:** a *Validation of record* bullet in this entry (the mutation campaign: rows killed, first failing test per row, base tree, sha256 of each file in section 10; and G1's result on the base tree), then the ledger regeneration again.

**`docs/development/roadmap.md`:** no row (the BF-900 contract's section 8 gives the grep).

**#1575:** the orchestrator notes "considered, deferred: the model calls that write no journal row" there (consult decision 4); this contract edits no GitHub state.

## 9. What this does NOT change

- The agentic loop's charge (`_execution_response_charge`, `_calibration_response_charge`, `_charge_discarded_response`, `agentic_loop.py:883-923`), its labels and its budget stop; `TurnCostBudget`, AD-1208, AD-1323 to AD-1325 (their policies and defaults; they read the loop's outcomes, which BF-680 already labels).
- The counts on any `LLMResponse`; cache replays and error responses (`usage_reported` stays `None`); `MockLLMClient` (considered, deferred, section 8).
- The journal, the sub-task chain, the one-shot record sites (S2), the doctor view (S3), the Copilot proxy, price tables, configuration (no field; `config/system.yaml` untouched).

## 10. Mutation rows (whole stripped lines; each occurs once in its file after section 7)

Run against `tests/test_bf901_s1_token_accounting.py` on the contract-applied tree (BF-900 applied too), after an unmutated baseline run of that file that passes. The runner mutates each file in place and restores it before the next row.

| # | File | Line (stripped) | Mutate to | Killed by (the failing assertion) |
|---|---|---|---|---|
| L1 | `src/probos/cognitive/llm_client.py` | `usage_reported = "total_tokens" in usage` | `usage_reported = True` | P2: `assert response.usage_reported is False` |
| L2 | `src/probos/cognitive/llm_client.py` | `usage_reported = "prompt_eval_count" in data and "eval_count" in data` | `usage_reported = "eval_count" in data` | P6: `assert response.usage_reported is False` |
| L3 | `src/probos/types.py` | `usage_reported: bool | None = None` | `usage_reported: bool | None = False` | D1: `assert LLMResponse(content="x").usage_reported is None`; C1[unstated_counts] fails too (charged as an estimate) |
| TA1 | `src/probos/cognitive/token_accounting.py` | `if type(error) is str and error:` | `if False:` | C1[error]: the charge is `measured` 0, not `""` |
| TA2 | same | `reported = flag if type(flag) is bool else None` | `reported = None` | C1[absent_no_output]: the charge is `measured` 0, not `""` |
| TA3 | same | `if reported is not False and not (total == 0 and produced):` | `if reported is not False:` | C1[proxy_zeros]: the charge is `measured` 0, not the estimate |
| TA4 | same | `if not produced:` | `if False:` | C1[absent_no_output]: the charge is an estimate (`TokenCharge(100, 1, 101, "estimated")`), not `""` |
| TA5 | same | `completion_tokens=estimate - prompt,` | `completion_tokens=estimate,` | C2: `assert (...) == (100, 20, 120)` |
| TA6 | same | `return "unknown"` | `return ""` | A1[unknown_blank], A1[unknown_none], A1[unknown_mock] |
| TA7 | same | `total += max(1, len(text) // 4)` | `total += max(1, len(text) // 3)` | G1: `assert estimate_context([...]) == 100` |
| TA8 | same | `return bool((text or response.content or "").strip())` | `return bool(text or response.content or "")` | G1: `assert non_empty(LLMResponse(content="   ")) is False` |
| TA9 | same | `composed.append({"role": "user", "content": request.prompt})` | `pass` | R1[prompt_with_system], R1[prompt_without_system] |

Campaign of record: name the base tree and the sha256 of `llm_client.py`, `types.py`, `token_accounting.py` and the new test file; a later run whose hashes match does not repeat it. **G1 on the base:** the test file imports `probos.cognitive.token_accounting` at module scope, so it cannot be collected on the base. The orchestrator copies `test_the_moved_functions_return_the_base_integers` with the imports it uses (`agentic_loop_module`, `LLMResponse`, `TextBlock`, `ToolUseBlock`, `ToolCallRequest`) and the constant `REPLY` into a scratch file outside the repository and runs it against the base tree's source: it must pass, which is the evidence that the integers are the base's.

## 11. Verified Against Codebase (2026-10-21, tree `8c8bc441`)

`git diff --stat 3dfb6f81 HEAD -- src/probos/cognitive/llm_client.py src/probos/types.py src/probos/cognitive/swe_harness/agentic_loop.py src/probos/crew_execution_usage.py src/probos/cognitive/turn_cost.py tests/test_bf680_token_usage_fallback.py tests/test_ad1325_boundaries.py` printed nothing: no anchor moved since the consult.

| Consult anchor | On this tree | Evidence |
|---|---|---|
| `_call_openai` usage parse | TRUE (`:2415-2418`) | `llm_client.py:2415` `usage = data.get("usage", {})` ... `:2418` `completion_tokens = usage.get("completion_tokens", 0)`; constructor `:2420-2432` with `answered_model=_echoed_model(data),` last |
| Ollama parse | TRUE (`:2478-2480`) | `:2478` `prompt_tokens = data.get("prompt_eval_count", 0)`; `:2453` `"stream": False,`; constructor `:2482-2492` |
| No streaming | TRUE | Absence Verified below |
| `LLMResponse` | TRUE (`types.py:334-361`) | `:360` `answered_tier: str | None = None`; `:361` `answered_model: str | None = None`; `:364` `class EscalationTier(Enum):` |
| `replace` keeps fields | TRUE | `llm_client.py:1833` `response = replace(response, answered_tier=attempt_tier)` |
| Cache replays | TRUE | `llm_client.py:1526-1530`, `:2001-2010` (`cached=True`, `tokens_used=cached.tokens_used`) |
| `_completion_is_non_empty` | MOVED (`:996`) | `agentic_loop.py:996-1026` |
| `_estimate_call_tokens` | TRUE (`:1029`) | `agentic_loop.py:1029-1065`, then `:1068` `@dataclass`, `:1069` `class AgenticResult:` |
| `_estimate_context_tokens` and DD-3 | TRUE (`:926`, `:938-940`) | `agentic_loop.py:926-962`, then `:965` `def _largest_group_tokens(` |
| Loop imports | TRUE | `agentic_loop.py:22-33` (`TextBlock`, `ToolUseBlock` from `tool_call`), `:46-51` (`crew_execution_usage`, ending `merge_token_sources as _token_source_label,` / `)`), `:52` `from probos.cognitive.swe_harness.loop_tier_steps import (` |
| `TokenSource` | TRUE | `crew_execution_usage.py:11-14` |
| `AgenticResult.token_source` | MOVED (`:1098`) | `agentic_loop.py:1098` `token_source: str = TOKEN_SOURCE_MEASURED` |
| Turn cost wording | TRUE | `turn_cost.py:79` `_COST_STOP_ESTIMATED: str = " (usage estimated, not measured)"`; `:245-261` `record`; `:263-287` `render_stop`; `:127-135` constructor (`budget`, `max_total_iterations`) |
| Dispatch labels | MOVED | `agentic_dispatch.py:2266` `token_source: str = "measured"`, `:4118-4143` (unchanged by this contract) |
| The fixture exclusion | TRUE | `tests/test_ad1325_boundaries.py:227-232` |
| `ToolCallRequest` | TRUE | the `tool_call` module, `:669-676` (frozen, no `__post_init__`; `id` kept verbatim); `TextBlock` `:914-919`; `ToolUseBlock` `:923-927` |
| `LLMRequest` | TRUE | `types.py:306-331` (`prompt`, `system_prompt=""`, `messages=None`, `tools=None`) |
| The fake-provider shape | TRUE | `tests/test_llm_client.py:14-18` (`_httpx_response`), `:148-158` (`_make_config`); `_call_openai(self, request, model, client, *, timeout=...)` `llm_client.py:2276-2282` posts `client.post("chat/completions", json=payload, timeout=timeout)` `:2362` |
| Tracker anchors (after BF-900) | per BF-900 section 8 | `PROGRESS.md` line 1, blank line 2, then BF-900's entry; `DECISIONS.md` BF-900's *Reversal* line, a blank line, `### Explicit delegation models, ...` |

**Golden integers, worked.** `_estimate_context_tokens` sums `max(1, len(text) // 4)` per dict message, where `text` is the content plus `json.dumps(tool_calls, separators=(",", ":"), default=str)`. (1) 400 characters: 100. (2) 400 characters, a skipped string, an empty message (`max(1, 0)`): 101. (3) 8 characters plus `[{"id":"c1"}]` (13 characters): 21 // 4 = 5. (4) outbound 100 + completion `"t" * 40` plus `[{"id":"i","name":"n","arguments":{}}]` (38 characters): 78 // 4 = 19; 119. (5) outbound 100 + `"z" * 80` with no tool calls (an empty list is falsy, not serialised): 20; 120.

## Absence Verified (2026-10-21)

```
CLAIM: ProbOS never streams
RUN:   Grep "\"stream\":\s*True|stream\s*=\s*True|stream_options|\"stream\":\s*False" src/probos/   (A1, 2026-10-21)
FOUND: no key set to stream; "stream": False at __main__.py:297 (the Ollama model warm-up, :284-307),
       cognitive/llm_client.py:1352 (the Ollama probe) and :2453 (native chat; :2456 after S1)
HOLDS: yes (the first enumeration listed only the llm_client.py sites; __main__.py:297 dates from e419c1bb9)

CLAIM: nothing in src/ calls the three estimator names outside the loop
RUN:   Grep "_estimate_call_tokens|_completion_is_non_empty|_estimate_context_tokens" src/
FOUND: swe_harness/agentic_loop.py only (:892-893, :915-916, :926, :980, :996, :1029, :1051, :1063, :1476, :1494, :1785, :1986, :2113, :2430)
HOLDS: yes

CLAIM: no test monkeypatches _estimate_context_tokens or _completion_is_non_empty other than on the loop module
RUN:   Grep "_estimate_call_tokens|_completion_is_non_empty|_estimate_context_tokens" tests/
FOUND: monkeypatch.setattr only at test_bf680...:155-156 (_completion_is_non_empty), :281, test_ad1190...:1685, :1732, test_ad1200...:585 (_estimate_call_tokens), all on the loop module
HOLDS: yes

CLAIM: the new names are free
RUN:   Grep "class TokenCharge|usage_reported" --glob "*.py" (repository); Grep "token_accounting|answered_model_name|charge_completion|request_messages" src/probos/
FOUND: nothing; nothing
HOLDS: yes

CLAIM: only one test serialises a whole LLMResponse
RUN:   Grep "fields\(LLMResponse|LLMResponse\.__dataclass_fields__|asdict\(resp|asdict\(response" --glob "*.py"
FOUND: tests/test_ad1325_boundaries.py:230
RUN:   Grep "\"refusal_cause\"" tests/fixtures/
FOUND: tests/fixtures/ad1325_ad1324_flag_off_base.json (that test's fixture)
HOLDS: yes

CLAIM: no test compares a whole LLMResponse with ==
RUN:   Grep "== LLMResponse\(|LLMResponse\(.*\) ==" tests/
FOUND: nothing
HOLDS: yes

CLAIM: no source scan of agentic_loop.py pins the moved definitions
RUN:   Grep "agentic_loop\.py|getsource\(agentic_loop|agentic_loop_module\.__file__|loop_module\.__file__" tests/
FOUND: fixtures/ad1152_agentic_off_golden.json:6 (a base-commit blob record, not compared: test_ad1152_agentic_correlation.py:496-503 compares the observation only),
       test_ad1190_delegation_tree_budget.py:1957 (stop-reason census of the module's AST: unchanged), test_ad1320...:663 (files containing "budget_awareness_state": the new module has none), test_ad1324_srp_layout.py:22, :51 (AgenticLoop's methods: unchanged)
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| srp-size | `token_accounting.py` is about 200 lines with one small dataclass. `AgenticLoop` (baseline `lines`, `architecture-baseline.yaml:649-654`; `test_ad1324_srp_layout.py` caps its methods at 13) is not touched: the moved functions are module-level. `OpenAICompatibleClient` (baseline `lines`, `methods`, `:580-585`) gains 6 lines and no method |
| layer-import | `cognitive -> cognitive.swe_harness` (same layer) and `cognitive -> probos.crew_execution_usage` (not a ranked package; the loop already imports it, `agentic_loop.py:46`); `tests/test_layer_boundaries.py` runs in M3 |
| db-connect, unowned-task | none |
| config reference and facade | no config field; `config/system.yaml` untouched |
| seam contracts | `Grep "_estimate|_completion_is_non_empty|LLMResponse|_call_openai|_call_ollama" docs/development/seams/` finds nothing |
| store registry | no store |
| AD-1343 seam census | no `.complete(` call added (`test_ad1343_seam_registry.py` in M3) |
| Hidden pins | `tests/test_ad1325_boundaries.py:229-232` (section 7.5); AD-1152's golden observation (consumer test, M1) |
| Ledger | M4 |

## 13. Prior Art and Blind Spots

- **OpenTelemetry GenAI semantic conventions** ([opentelemetry.io](https://opentelemetry.io/docs/specs/semconv/gen-ai/openai), [OpenObserve guide](https://openobserve.ai/blog/opentelemetry-genai-semantic-conventions.md)): token counts are `gen_ai.usage.input_tokens` / `output_tokens`, and the model is recorded twice, `gen_ai.request.model` (asked) and `gen_ai.response.model` (served). **Adopted:** the answered-model preference (D7) follows the same split, which AD-1327 already carries. **Not adopted:** the conventions have no "estimated" provenance; ProbOS's `TokenSource` stays.
- **Ollama omitting `prompt_eval_count`** (the consult's sources: [LiteLLM's Ollama handler history](https://git.kvant.cloud/phoenix/litellm-mirror/commits/commit/03d61d97fe6f646f990899a5ded7c237e3fb2d95/litellm/llms/ollama.py), [Ollama prompt caching](https://leanpub.com/read/ollama/prompt-caching)): handled by requiring both keys (D3).
- **Internal:** BF-680 (#1078) set the rule; AD-1142 DD-3 the estimator; AD-1327 `answered_model`.
- **Blind spots:** a partial Ollama count (completion present, prompt absent) is discarded for a whole estimate rather than labelled mixed (accepted: simpler, labelled); `request_messages` does not count the per-tier system suffix or resolved attachments (an estimate; documented).
- Reference projects (`docs/research/reference-projects.md`, judged against 2026-10-21): none of its rows covers token accounting; AG-UI (never) and MCP Apps (2026-04-08) are overdue and considered, deferred. Row to add (the orchestrator's call; this contract edits only itself): "OpenTelemetry GenAI semantic conventions | 2026-10-21 | passing | BF-901 S1 Prior Art" under Protocols and standards.

## 14. Diff Reviewer: properties to verify

1. The bodies of the three moved functions in `token_accounting.py` are character-for-character the base's bodies; only the two docstring passages D2 names differ.
2. `agentic_loop.py` binds the three names at module scope by `from ... import`, defines none of them, and calls them unqualified, as before.
3. `_call_openai` and `_call_ollama_native` compute the counts exactly as on the base; the only additions are `usage_reported` and its keyword.
4. No code in `agentic_loop.py` reads `usage_reported`.
5. `charge_completion` never returns `source="measured"` for an error response, nor for a reply with no output whose transport reported no usage.
6. `charge_completion` returns the reported counts unchanged whenever it labels them measured and each is a non-negative exact `int`; any other count is charged as 0 (`_count`, D6). S1 has no production caller, so a malformed count is reachable only by injection (A1, F3).
7. `answered_model_name` never returns an empty or blank string.
8. The AD-1325 fixture still compares byte-exact, with only `usage_reported` added to the excluded keys.
9. G1 imports the functions from the loop module (so it runs on the base), and its integers match the arithmetic in section 11.

## 15. Acceptance criteria

1. One owner: the three functions exist only in `token_accounting.py`, and the loop's names are the same objects (G2); the loop's behaviour is unchanged (G1, X3, BF-680's tests, AD-1152's golden observation).
2. The transport records presence for both formats and leaves the counts as reported (P1 to P6, L1, L2).
3. A missing count is never charged as a measured 0: absent usage with output is estimated, absent usage without output is `""` (C1, TA2 to TA4).
4. A budget decision made on estimated tokens says so (X1), and a measured one does not (X2).
5. The streamed clause is recorded as not applicable, with the search that shows it (section 2, DECISIONS).
6. Every mutation row in section 10 is killed by the named assertion, and G1 passes on the base.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-10-21, Diff Reviewer round 1)

Round 1 (GPT-6.1 Sol) verified all nine section 14 properties and found three P3 wording defects; none changes behaviour.

- **F1 (ordinary reach).** `usage_reported` was described as "no count keys" for `False` with zero counts. The predicates are narrower: OpenAI format tests only the `total_tokens` key; Ollama native needs both count keys. So `False` can sit beside a nonzero partial count (`eval_count` alone: `(0, 5, 5, False)`, pinned by P6), and an OpenAI `True` can carry only a total (`(0, 0, 11, True)`). Rewritten: the `types.py` comment (section 7.3), D3, and the DECISIONS D3-D4 bullet (section 8).
- **F2 (ordinary reach).** The streaming census missed the Ollama model warm-up payload in `__main__.py`. Corrected in section 2, Absence Verified and the DECISIONS *Not applicable* bullet. The conclusion (ProbOS never streams) is unchanged.
- **F3 (injected-only, not repaired).** The measured branch normalises counts through `_count`, so "the counts unchanged" holds only for non-negative exact `int`s. Qualified: the `charge_completion` docstring (section 7.1), D5 and section 14 property 6. No code or test is added; it is recorded in the follow-up register.
- **Unchanged.** Every code line (the A1 edits to `types.py` and `token_accounting.py` are comment and docstring text only), both parsers, every count value, the tests and section 6's test count, the section 10 mutation rows, the PROGRESS entry, and the anchors S2 relies on (the PROGRESS head and the DECISIONS *Reversal* line).
