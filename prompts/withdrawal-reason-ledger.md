# A judged withdrawal is recorded apart from a lost action, with its reason, and a retried think settles once

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-17
**Status:** ready to build on `origin/main` `4f10b15f7e5acb08340e46f46ea3adf23d6005d1`. Every anchor below was read on that commit. `git log --oneline 5275d008..HEAD` over `action_billets.py`, `action_accounting.py`, `proactive.py`, `cognitive_agent.py`, `output_grounding.py`, `tests/test_bf934_s1_decision_routing.py`, `tests/test_bf934_s3_intended_actions_ledger.py` and `tests/bf934_world.py` prints nothing, so the issue's anchors (filed on `5275d008`) hold. Open PR #1825 touches no Python file. **Owning issue:** #1807 (BF-976, already allocated). Commits say `Refs #1807.` Save this contract as `prompts/withdrawal-reason-ledger.md`.
**Dependencies:** none.
**Estimated tests:** 36 cases in one new file, `tests/test_bf976_withdrawal_ledger.py`: 21 `built`, 2 controls and the thirteen cases of b9, which R2 adds and R7 and R8 extend (b9 is not `built`: eight of its cases pass on the base, because they pin what the base does with a marker inside or across a block). No existing test is edited.

## 1. Problem

1. The billet (`cognitive/action_billets.py:66-68`) tells a model that judges a decided proposal or notebook entry unsupported to "answer exactly [NO_RESPONSE]; that withdrawal is recorded." That is the same output as a decision the model forgot. Both end at the pure-silence settle (`proactive.py:1533`) with reason `no_response`, which is in `PRE_EXTRACTION` (`action_accounting.py:52`). So #1673's live re-measure cannot tell a judgement from a loss.
2. A `[WITHDRAWN] <reason>` line written without `[NO_RESPONSE]` skips the silence gate (`proactive.py:1460` tests the token). BF-203's regex (`proactive.py:3971`) then removes the tag and leaves the reason, which is posted as an observation. The orchestrator measured this with a probe on this tree: the thread title was `[Observation] evidence changed`.
3. AD-576b calls `agent.handle_intent(intent)` up to three times with one intent (`proactive.py:1402-1419`). Each attempt's triage writes a `declared` row (`record_declared`, `action_accounting.py:96-114`, called at `cognitive_agent.py:6541`), and the loop settles only the last attempt. The issue decides not to change the writes. #1673's reopening comment already changed step 5 of the re-measure to count only the latest declared row per agent and correlation id. No test pins the behaviour: `tests/test_combo_a_ad576b_retry.py` only scans the source.

**Where the withdrawal is taught.** The billet is built at one site, `cognitive_agent.py:11550` (`_decided = decision_billet(observation.get("_intended_actions"))` in `_build_user_message`), the single call's prompt. COMPOSE never sees it. The chain's rewriters are therefore recorded as limits (L2, L3), not edited.

## 2. Solution overview

- **Syntax.** The billet asks for `[NO_RESPONSE]` and, on the next line, `[WITHDRAWN]` followed by one plain sentence on why.
- **Parser.** One constant and one parser are added to `action_billets.py`: `WITHDRAWN_MARKER`, `WITHDRAWAL_REASON_CHARS = 200` and `withdrawal_reason(text) -> str | None`.
- **Loop (`proactive.py`).** The marker silences an output just as the token does, with or without the token. It is read outside the output's proposal and notebook blocks (D8), so a marker inside one is that block's own text:
  - an output with the line and no valid block settles at `:1533` with reason `withdrawn`;
  - an output with the line and a valid block has its blocks carried out and its text cleared, then settles at `:1569` with `withdrawn`;
  - the text never reaches `_post_to_ward_room`.
- **Ledger (`action_accounting.py`).** `"withdrawn"` joins `PRE_EXTRACTION`, so every intended block tag that nothing carried out keeps the reason. The dropped row's `data` carries `withdrawal`, the parsed reason. The row's `detail` and the log line carry only `withdrawn`. A withdrawal is logged at INFO, since it is not a lost decision.
- **Retries.** No change to the code. A control seam test pins two declared rows, one correlation id and one settlement.

Rejected designs:
- **A new silence token** (the issue rejected it): `[NO_RESPONSE]` has many readers in `src`, and each would need to learn it.
- **Teaching the line to COMPOSE and REFLECT and keeping it through every rewriter.** That touches five sites in the chain for a path the billet does not reach. The issue's own rule covers it: where the chain strips the line, the withdrawal records as `no_response`, which over-counts loss and never hides it.
- **Settling superseded attempts.** The issue rejected it: a `None` result carries no metadata.
- **Stripping the marker line and posting the rest of a token-less output.** That needs a second strip rule beside BF-203's, and it contradicts the billet, where the withdrawal covers the turn's observation (D4).
- **Stripping every marker line from the output before the extractor reads it** (review round 1, F1; the reviewer's smallest repair). A proposal whose title holds the marker would lose its title and be refused, where the base files it, and the ledger would still record `withdrawn` for an action the model never withdrew.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | **The parser.** `withdrawal_reason(text: str) -> str \| None`. It finds the first `[WITHDRAWN]` anywhere in the text it is given (the loop gives it the output without its proposal and notebook blocks, D8), upper case only, and returns the rest of that line up to the first `"\n"`. Each character with `str.isprintable()` False becomes a space; whitespace runs collapse to one space; the result is cut to 200 code points (Python `str` length) with `.rstrip()` and no ellipsis. It returns `None` when there is no marker. A marker with no reason returns `""`, which is still a withdrawal. With two markers, the first wins. | "Anywhere" matches how the loop reads `[NO_RESPONSE]` (a substring test, `:1460`), and BF-203 would post a mid-line marker's reason just as it posts a line-start one. Upper case matches the taught form and BF-203's tag shape. A lower-case marker is not read (L5). `isprintable` removes controls, format characters, lone surrogates and the line and paragraph separators, so the reason is one physical line that UTF-8 can encode. |
| D2 | **The billet clause** (P2-2), word for word: `If you find that the evidence no longer supports an action, withdraw it: write [NO_RESPONSE] on one line and, on the next, [WITHDRAWN] followed by one plain sentence on why. That withdrawal is recorded with its reason.` | It carries no hex-looking run and repeats no triage word (`action_billets.py:53-55`); the marker comes from the constant. "Plain sentence" asks for no identifiers, which lowers the BF-204 case (L1). |
| D3 | **How the text travels.** `unaccounted(..., reason, *, withdrawal: str \| None = None)` and `settle_intended_actions(..., reason, *, withdrawal: str \| None = None)`. A drop whose final reason is `withdrawn` gets `drop["withdrawal"] = withdrawal`, and the row's `data` holds it. `detail` stays `"<callsign> intended <action>: <reason>"`. The log line is unchanged and logs at INFO when the reason is `withdrawn`. | Keyword-only with a default, so the other five call sites and the existing tests (`test_bf934_s3...py:248,268,314`, positional) stay as they are. The model's text lives in one governed place, the row's `data`, and not in the log. **Size:** at most 200 printable code points is at most 800 bytes under the governed reader's measure (`event_log.py:319-327`: UTF-8, `ensure_ascii=False`; 4 bytes for a code point outside the BMP, 2 for `"` or `\`), and at most 2400 bytes as stored (`event_log.py:659`, ASCII escapes, 12 bytes outside the BMP). The caps are 512 characters a string (`:34`), 4096 bytes a row (`:36`) and 16384 raw (`:35`). b7 measures it. |
| D4 | **The sites.** `:1460` silences on `"[NO_RESPONSE]" in text or withdrawal_outside_blocks(text) is not None` (D8). `:1533` settles `withdrawn` when the line is present, else `no_response`. `:1536` `_withdrawn` becomes that same condition. `:1569` settles `withdrawn` when the line is present, else as before. The other sites stay as they are: `:1449` (no output read) and `:1547` (`raw_intent_json`: an output that opens with a raw intents object; a silenced output reaches it only when it also carries a valid block, and its reason is then `raw_intent_json` with the line or the token alike, with no withdrawal text recorded, as the token's is on the base; the orchestrator's probe measured this on the M2 tree). `:1581`, `:1595` and `:1614` cannot be reached with a withdrawal, because a silenced output either returns at `:1533`, or returns at `:1547`, or has its text cleared at `:1558-1559` and returns at `:1569`. | At `:1569` the output carries a valid block and the line: the blocks are carried out, and an intended action the output did not carry out was judged, not lost (b3). A token-less marker withdraws like the token: its line never posts, and an observation beside it is not posted (L6). |
| D5 | **Tests.** A real EventLog, a real Ward Room and the real think cycle (`tests/bf934_world.py`). The Ward Room claim is asserted on the Ward Room itself: `threads(w)` titles, plus every thread's title and body and every post's body. The retry seam swaps `probos.proactive`'s module-global `asyncio` for a shim whose `sleep` records its delay and returns at once; every other name delegates to `asyncio`. | The shim is narrower than patching `asyncio.sleep` process-wide: the Ward Room, the EventLog and the agent keep their real sleeps, and the recorded `[0.5]` proves that exactly one backoff ran. |
| D6 | **The BF-934 contract.** Add a dated note under its D2 heading. Do not edit mutation row 46 or L15. | Row 46 and L15 record the campaign and measurements of the tree that contract built. Editing them would make its record false. The note states what moved. |
| D7 | **Nothing is persisted beyond one optional key in a `dropped` row's `data`, and no config field, flag or baseline changes.** | See Absence Verified. `ProactiveCognitiveLoop`'s srp-size row already carries `lines` and `methods` (`architecture-baseline.yaml:862-867`), and no method is added. The EventLog pair census (`test_ad1195_eventlog_pair_freeze.py:109-110`) pins `(category, event)` pairs, which are unchanged. |
| D8 | **Where the loop reads the line (review rounds 1 and 2, F1 and F2).** `withdrawal_outside_blocks(text)` in `proactive.py`, next to `carries_actionable_block`: `withdrawal_reason` of the text in which each notebook block (`_NOTEBOOK_PATTERN`) and then each strict proposal block (`PROPOSAL_PATTERN`, `re.DOTALL`) has been replaced by a line break: the two patterns the extractor strips with, in its order, a block it files and one it refuses alike. The extractor also removes `[READ_NOTEBOOK]` tags and `[NOTE]` blocks between the two passes, which the helper does not (L7). The line break keeps the neighbours of a removed block apart: `[WITH`, a block and `DRAWN]` read as no marker, and a reason ends where a removed block begins (b9: split-by-proposal, split-by-notebook, reason-before-block). It is a line break for the parser only. While the blocks are found each removed block is a form feed (`_BLOCK_BREAK`): the extractor joins the text around a removed notebook block, and a line break there would make a strict closer that the joined text lacks, or close a block early that the joined text closes later (b9: closer-after-notebook, early-closer-after-notebook). A form feed is whitespace, which the proposal pattern passes over as it passes over the join, and it is not a line break. A form feed in the text itself is a space first, as the parser reads it (b9: form-feed-in-reason). The parser is unchanged, and the helper is a function of the module, not a method of the loop. | A marker inside a block the loop carries out is that block's own text. Read as a withdrawal, it recorded `withdrawn` and the title or rationale as the reason for an action the model never withdrew (a forgotten action looked judged), and it withdrew the observation beside the block. The orchestrator's probe on M2: with the marker in the title of a filed proposal, an unfiled notebook entry recorded `withdrawn` with the title's text where the base recorded `no_block_executed`; the Ward Room thread and the notebook file were the ones the base writes. A marker in any other kind of block, or in a `[PROPOSAL]` that the pattern does not match, is still read (L7). Round 2 found that removing a block with nothing in its place joined its neighbours: the orchestrator's probe on R6 showed `[WITH`, a proposal block and `DRAWN] x` recording `withdrawn` with the reason `x`, where the base records no withdrawal. The line break that R7 put in place of each removed block still differed from the extractor's own stripping, which the orchestrator found by comparing the two before round 3: the line break made a strict closer that the joined text lacks (a marker outside any block was hidden) and closed a block early that the joined text closes later (a marker inside one was read). An exhaustive comparison of the helper with the extractor's stripping, over all 5,380,839 sequences of up to seven pieces of the block vocabulary (tags, closers, a notebook block, a marker and plain text), differs only where the removal of a notebook block completes a proposal tag or closer (1,374 sequences; L7); the line break differed in 944 other sequences of up to six pieces. |

## 4. Milestones and commits

The Builder is `claude-sonnet-5.5`, with at most about 150 tool calls per milestone. It searches first, then reads the range. It runs no tests; the orchestrator runs every command in section 8. Stage only the named files and never use `git add -A`. Every SEARCH must match exactly once, at a line start, at its turn; if one does not, stop and report.

- **M1:** P1-1.
  - Subject: `Withdrawal ledger tests: a judged withdrawal is recorded with its reason and its line is not posted (expected failures until the build)`
  - Body: `Adds 21 cases that fail on the base at their own assert, marked strict expected failures until the build, and two controls that pass on the base: a bare silence after a proposal billet still records no_response, and a retried think writes one declared row per attempt under one correlation id and settles once.` Then `Refs #1807.` and the trailer.
- **M2:** P2-1 and P2-2 (`action_billets.py`), P2-3 to P2-6 (`action_accounting.py`), P2-7 to P2-10 (`proactive.py`), P2-11 (the marker becomes a no-op).
  - Subject: `A judged withdrawal is recorded with its reason, and its line does not reach the Ward Room`
  - Body: `The billet asks for [NO_RESPONSE] and a [WITHDRAWN] line with one sentence on why. One parser reads the first such line and cuts its reason to 200 printable code points. The proactive loop treats the line like the silence token: the observation is not posted, a valid block beside it is still carried out, and each intended action nothing carried out is recorded with reason withdrawn, logged at INFO, with the reason in the dropped row's data.` Then `Refs #1807.` and the trailer.
- **M3:** P3-1, P3-2 and P3-3.
  - Subject: `Trackers for the withdrawal reason in the intended-actions ledger`
  - Body: `PROGRESS.md and DECISIONS.md entries, and a dated note in the earlier ledger contract.` Then `Refs #1807.` and the trailer.
- **R1 to R9 (review rounds 1 and 2 and the orchestrator's own check before round 3; made by the orchestrator, not the Builder):** R1 is the first campaign of record and three corrections to this contract's text. R2 repairs finding F1: the pairs of 6.4 (`proactive.py`, the test file, `PROGRESS.md`, `DECISIONS.md`), this contract's corrections to the header and to sections 2, 3, 4, 5, 8.2, 8.3, 9, 11 and 13, and the regenerated ledger pair. R3 is the campaign of record on R2's head. R4 corrects what R2 said of its case b9, which is not a `built` case: the marker and the docstrings in the test file (the pairs of 6.5) and this contract's header, D1, section 4 and 8.3. R5 is the campaign of record on R4's head (20 rows), a bullet that replaces R3's in `DECISIONS.md`, and the regenerated ledger pair. R6 corrects the last clause of L7 (what runs when a marker that the helper does not strip withdraws a turn); it changes this contract and the ledger pair only. R7 repairs finding F2 of review round 2 (removing a block joined its neighbours): the pairs of 6.6 (`proactive.py`, the test file, `PROGRESS.md`, `DECISIONS.md`), this contract's corrections to the header, D8, L7 and sections 4, 8.2, 8.3 and 9, and the regenerated ledger pair. R8 repairs two divergences from the extractor that the orchestrator's own comparison found in R7's helper before round 3 (the line break made a strict closer that the joined text lacks and closed a block early): the pairs of 6.7 (`proactive.py`, the test file, `PROGRESS.md`, `DECISIONS.md`), this contract's corrections to the header, D8, L7 and sections 4, 6.6, 8.2, 8.3, 9 and 13, and the regenerated ledger pair. R9 is the campaign of record on R8's head (25 rows), a bullet that replaces R5's in `DECISIONS.md`, and the regenerated ledger pair.

I checked the three subjects and bodies by eye for the issue's list of closing words, including inside other words, and for `AD-` and `BF-` tokens. They contain none.

## 5. Behaviour table (the reply as `proactive.py` reads it; the triage intends `proposal`)

| Reply | Base: settlement, Ward Room | After M2 and R2 |
|---|---|---|
| `[NO_RESPONSE]` | `no_response`; nothing posted | same (c1) |
| `[NO_RESPONSE]\n[WITHDRAWN] evidence changed` | `no_response`; nothing posted | `withdrawn`, `data.withdrawal="evidence changed"`; nothing posted (b1, b2) |
| `[WITHDRAWN] evidence changed` | posted: `[Observation] evidence changed`; `no_block_executed` | `withdrawn`; nothing posted (b2) |
| observation + `\n[WITHDRAWN] evidence changed` | observation and reason posted | `withdrawn`; nothing posted (b2, L6) |
| `[WITHDRAWN] ...` + valid proposal, triage also intends `notebook` (with and without the token) | with the token: proposal filed, notebook `no_response`; without it, the reason is posted too | proposal filed; notebook `withdrawn`; reason not posted (b3) |
| a valid proposal whose title or rationale holds `[WITHDRAWN] evidence changed`, triage also intends `notebook` | proposal filed as written; notebook `no_block_executed` | the same as the base: the marker is the block's own text (b9) |
| a valid notebook block with the marker inside, triage intends `proposal` and `notebook` | proposal `no_block_executed` | the same as the base (b9) |

## 6. The contract

### 6.1 M1: new test file

**P1-1** (`tests/test_bf976_withdrawal_ledger.py`: new file)

```python
"""BF-976 (#1807): a judged withdrawal is recorded apart from a lost action, its line does not reach the Ward Room, and a retried think settles once.

Real: the think cycle, the extraction, the Ward Room and Ship's Records on tmp_path, an EventLog on tmp_path and, where a case calls ``crew``, the cognitive
agent's lifecycle with the single call. Doubles (tests/bf934_world.py): the model, the triage's handlers, and a thinker whose ``handle_intent`` answers a fixed
text with the ``intended_actions`` metadata the lifecycle would attach. The ``built`` cases fail on the base at their own assert; the two controls pass on both.
No name that M2 adds is imported at module level. Each docstring names the mutation rows (contract section 8.3) the case kills.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import probos.cognitive.action_accounting as accounting
import probos.cognitive.action_billets as billets
import probos.proactive as proactive
from probos.protocols import EventLogQuerySpec
from probos.types import IntentResult
from tests.bf934_world import DECIDED, crew, think, thinker, threads, world

# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1807: a withdrawal is recorded as no_response until M2")

PROPOSAL = "[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]"
WITHDRAWAL = "[NO_RESPONSE]\n[WITHDRAWN] evidence changed"
EMOJI = "\U0001F600"  # a code point outside the BMP: 4 bytes in UTF-8, 12 as a JSON ASCII escape


def _parser():
    """M2's parser. Until then this fails at its own assert, as the xfail marker requires."""
    parse = getattr(billets, "withdrawal_reason", None)
    assert parse is not None, "withdrawal_reason is built by M2"
    return parse


async def _rows(w, event: str) -> list[dict]:
    """The EventLog rows of the intended_actions category, oldest first."""
    return list(reversed(await w.events.query_structured(category="intended_actions", event=event, limit=200)))


def _drops(rows: list[dict]) -> list[tuple[str, str, str | None]]:
    return [(r["data"]["action"], r["data"]["reason"], r["data"].get("withdrawal")) for r in rows]


async def _ward_room_text(w) -> list[str]:
    """Every thread's title and body and every post's body, in every channel."""
    texts: list[str] = []
    for channel in await w.ws.list_channels():
        for thread in await w.ws.list_threads(channel.id, limit=500):
            texts += [thread.title, thread.body]
            texts += [str(post.get("body", "")) for post in (await w.ws.get_thread(thread.id))["posts"]]
    return texts


def _said(caplog, message: str) -> list[str]:
    """The levels at which the accounting module logged a line containing *message*."""
    return [r.levelname for r in caplog.records if r.name == "probos.cognitive.action_accounting" and message in r.getMessage()]


class _InstantBackoff:
    """``probos.proactive``'s ``asyncio`` with AD-576b's backoff made instant and recorded; every other name is asyncio's own."""

    def __init__(self, slept: list[float]) -> None:
        self._slept = slept

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def sleep(self, delay: float, result: Any = None) -> Any:
        self._slept.append(delay)
        return result


async def test_control_a_bare_silence_after_a_proposal_billet_is_still_no_response(tmp_path):
    """Rows R2 and R12."""
    async with world(tmp_path, event_log=True) as w:
        agent, model = await crew(w, ["proposal"], lambda request: "[NO_RESPONSE]")
        await think(w, agent)
        assert len(model.requests) == 1 and DECIDED in model.requests[0].prompt and len(await _rows(w, "declared")) == 1  # premise
        assert _drops(await _rows(w, "dropped")) == [("proposal", "no_response", None)]


async def test_control_a_retried_think_declares_once_per_attempt_under_one_correlation_id_and_settles_once(tmp_path, monkeypatch):
    """Row R16. Passes on the base: it pins AD-576b's retry as #1673's re-measure reads it (the latest declared row per agent and correlation id)."""
    slept: list[float] = []
    monkeypatch.setattr(proactive, "asyncio", _InstantBackoff(slept))
    settled: list[str] = []
    real_settle = proactive.settle_intended_actions

    async def settle(*args: Any, **kwargs: Any) -> Any:
        settled.append(args[5])  # the reason: every call site passes it as the sixth positional argument
        return await real_settle(*args, **kwargs)

    monkeypatch.setattr(proactive, "settle_intended_actions", settle)
    async with world(tmp_path, event_log=True) as w:
        agent, model = await crew(w, ["proposal"], lambda request: "[NO_RESPONSE]")
        real = agent.handle_intent
        attempts: list[IntentResult] = []

        async def flaky(intent: Any) -> IntentResult:
            result = await real(intent)  # the triage runs and writes its declared row
            attempts.append(result)
            if len(attempts) == 1:  # a transient model error after the triage: AD-576b retries it
                return IntentResult(intent_id=intent.id, agent_id=agent.id, success=False, error="LLM connection error", metadata=result.metadata)
            return result

        agent.handle_intent = flaky
        await think(w, agent)
        assert len(attempts) == 2 and len(model.requests) == 2 and slept == [0.5]  # premise: two attempts, one backoff, no wall-clock wait
        assert attempts[0].metadata.get("intended_actions") == ["proposal"]
        declared = await _rows(w, "declared")
        assert len(declared) == 2 and {r["data"]["path"] for r in declared} == {"single_call"}
        assert len({r["correlation_id"] for r in declared}) == 1
        assert settled == ["no_response"]
        dropped = await _rows(w, "dropped")
        assert _drops(dropped) == [("proposal", "no_response", None)] and dropped[0]["correlation_id"] == declared[0]["correlation_id"]


@built
async def test_a_withdrawal_after_a_proposal_billet_is_recorded_as_withdrawn_with_its_reason(tmp_path):
    """The issue's first acceptance case. Rows R6, R7, R8, R9 and R11 (the issue's own: the withdrawal mapped back to no_response)."""
    async with world(tmp_path, event_log=True) as w:
        agent, model = await crew(w, ["proposal"], lambda request: WITHDRAWAL if DECIDED in request.prompt else "[NO_RESPONSE]")
        await think(w, agent)
        declared = await _rows(w, "declared")
        assert len(model.requests) == 1 and DECIDED in model.requests[0].prompt and len(declared) == 1  # premise: the billet's call answered
        assert "[WITHDRAWN]" in model.requests[0].prompt  # the billet teaches the line
        dropped = await _rows(w, "dropped")
        assert _drops(dropped) == [("proposal", "withdrawn", "evidence changed")]
        assert dropped[0]["correlation_id"] == declared[0]["correlation_id"] and dropped[0]["detail"] == "Kira intended proposal: withdrawn"
        assert await threads(w) == []


@built
@pytest.mark.parametrize("reply", [
    WITHDRAWAL,
    "[NO_RESPONSE] [WITHDRAWN] evidence changed",
    "[WITHDRAWN] evidence changed",
    "The coolant loop needs a second reading, said the log.\n[WITHDRAWN] evidence changed",
])
async def test_the_withdrawal_line_never_reaches_the_ward_room(tmp_path, reply):
    """The issue's second acceptance case. Rows R7, R8, R9, R11; R13 (the two replies without the token)."""
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, reply, {"intended_actions": ["proposal"]}))
        assert _drops(await _rows(w, "dropped")) == [("proposal", "withdrawn", "evidence changed")]
        assert await threads(w) == [] and not any("evidence changed" in text for text in await _ward_room_text(w))


@built
@pytest.mark.parametrize("token", ["[NO_RESPONSE]\n", ""])
async def test_a_withdrawal_beside_a_valid_block_files_the_block_and_records_the_rest_as_withdrawn(tmp_path, token):
    """The settle at proactive.py:1569. Rows R3, R7, R8, R9, R15; R13 and R14 (the reply without the token)."""
    async with world(tmp_path, event_log=True) as w:
        reply = f"{token}[WITHDRAWN] the notebook entry can wait\n{PROPOSAL}"
        await think(w, thinker(w, reply, {"intended_actions": ["proposal", "notebook"]}))
        assert await threads(w) == ["[Proposal] Cache the roster"]
        assert _drops(await _rows(w, "dropped")) == [("notebook", "withdrawn", "the notebook entry can wait")]
        assert not any("can wait" in text for text in await _ward_room_text(w))


@built
async def test_a_withdrawal_is_logged_at_info_and_its_text_stays_out_of_the_log(tmp_path, caplog):
    """Rows R7, R10 and R11."""
    async with world(tmp_path, event_log=True) as w:
        with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
            await think(w, thinker(w, WITHDRAWAL, {"intended_actions": ["proposal"]}))
        assert _said(caplog, "intended proposal and nothing carried it out: withdrawn") == ["INFO"]
        assert not any("evidence changed" in r.getMessage() for r in caplog.records if r.name == "probos.cognitive.action_accounting")


@built
@pytest.mark.parametrize("text, reason", [
    (WITHDRAWAL, "evidence changed"),
    ("[NO_RESPONSE]", None),
    ("", None),
    ("[NO_RESPONSE]\n[WITHDRAWN]", ""),
    ("[NO_RESPONSE]\n[WITHDRAWN] \t evidence\x00 changed \r\nThe next line.", "evidence changed"),
    ("[WITHDRAWN] first reason\n[WITHDRAWN] second reason", "first reason"),
    ("[NO_RESPONSE]\n[withdrawn] lower case", None),
    ("[NO_RESPONSE] [WITHDRAWN] on the same line", "on the same line"),
    ("[WITHDRAWN] one\u2028two", "one two"),
])
def test_the_parser_reads_the_first_withdrawal_line(text, reason):
    """Rows R1, R2, R3 and R4."""
    assert _parser()(text) == reason


@built
@pytest.mark.parametrize("body, reason", [
    ("evidence changed, " * 30, ("evidence changed, " * 12)[:200]),
    (EMOJI * 300, EMOJI * 200),
])
def test_the_reason_is_cut_to_200_code_points(body, reason):
    """Row R5."""
    assert getattr(billets, "WITHDRAWAL_REASON_CHARS", None) == 200
    assert _parser()("[WITHDRAWN] " + body) == reason and len(reason) == 200


@built
async def test_a_longest_reason_of_four_byte_characters_is_stored_and_read_back_whole(tmp_path):
    """The row-size bound of D3. Rows R5, R7, R8 and R9."""
    assert "withdrawal" in inspect.signature(accounting.settle_intended_actions).parameters
    reason = _parser()("[WITHDRAWN] " + EMOJI * 300)
    async with world(tmp_path, event_log=True) as w:
        drops = await accounting.settle_intended_actions(
            w.rt, thinker(w, ""), "intent-1", {"intended_actions": ["proposal"]}, [], "withdrawn", withdrawal=reason)
        assert [(d["action"], d["reason"], d.get("withdrawal")) for d in drops] == [("proposal", "withdrawn", EMOJI * 200)]
        assert _drops(await _rows(w, "dropped")) == [("proposal", "withdrawn", EMOJI * 200)]
        now = datetime.now(timezone.utc)
        batch = await w.events.query_governed(EventLogQuerySpec(
            start_time=now - timedelta(hours=1), end_time=now + timedelta(minutes=1), category="intended_actions", event="dropped", correlation_id=None,
            agent_id=None, limit=10, order="oldest_first", aggregate="none"))
        assert batch.truncated is False and [row.data["withdrawal"] for row in batch.rows] == [EMOJI * 200]


@built
def test_the_billet_teaches_the_withdrawal_line_and_its_reason():
    """Row R6."""
    assert getattr(billets, "WITHDRAWN_MARKER", None) == "[WITHDRAWN]"
    billet = billets.decision_billet(["proposal"])
    assert "withdraw it: write [NO_RESPONSE] on one line and, on the next, [WITHDRAWN] followed by one plain sentence on why." in billet
    assert "That withdrawal is recorded with its reason." in billet and "answer exactly [NO_RESPONSE]; that withdrawal is recorded." not in billet
```

### 6.2 M2: `action_billets.py`, `action_accounting.py`, `proactive.py` and the marker

**P2-1** (`src/probos/cognitive/action_billets.py`: the marker, the cap and the parser)
SEARCH:
```
BILLET_TAGS = (*_BLOCK_TAGS, *_COMPANION_TAGS)


def decision_billet(intended: Iterable[object] | None) -> str:
```
REPLACE:
```
BILLET_TAGS = (*_BLOCK_TAGS, *_COMPANION_TAGS)

#: BF-976 (#1807): the line that gives a withdrawal its reason, written after ``[NO_RESPONSE]``; the billet teaches it and ``withdrawal_reason`` reads it.
WITHDRAWN_MARKER = "[WITHDRAWN]"
#: The longest reason a withdrawal keeps, in code points (the length of a Python ``str``).
WITHDRAWAL_REASON_CHARS = 200


def withdrawal_reason(text: str) -> str | None:
    """The reason of the first withdrawal line in *text*, or None when *text* carries no ``WITHDRAWN_MARKER``.

    The marker counts wherever it stands, as ``[NO_RESPONSE]`` does for the proactive loop, and in upper case only. The reason is the rest of the marker's line, up
    to the first newline: each character that is not printable (``str.isprintable``: controls, format characters, surrogates, separators other than the space)
    becomes a space, runs of white space become one space, and the result is cut to ``WITHDRAWAL_REASON_CHARS`` code points with no ellipsis. So the reason is one
    line of at most 200 printable characters, and "" for a marker with no reason, which is still a withdrawal.
    """
    start = text.find(WITHDRAWN_MARKER)
    if start < 0:
        return None
    rest = text[start + len(WITHDRAWN_MARKER):].split("\n", 1)[0]
    cleaned = "".join(ch if ch.isprintable() else " " for ch in rest)
    return " ".join(cleaned.split())[:WITHDRAWAL_REASON_CHARS].rstrip()


def decision_billet(intended: Iterable[object] | None) -> str:
```

**P2-2** (the billet's withdrawal clause)
SEARCH:
```
        f"Before this step you decided to take these actions: {', '.join(named)}.",
        "That decision stands for this turn, so the usual default of silence does not apply here: carry it out with the blocks below, "
        "after any observation text you also write. If you find that the evidence no longer supports an action, answer exactly "
        "[NO_RESPONSE]; that withdrawal is recorded.",
```
REPLACE:
```
        f"Before this step you decided to take these actions: {', '.join(named)}.",
        "That decision stands for this turn, so the usual default of silence does not apply here: carry it out with the blocks below, "
        "after any observation text you also write. If you find that the evidence no longer supports an action, withdraw it: write "
        f"[NO_RESPONSE] on one line and, on the next, {WITHDRAWN_MARKER} followed by one plain sentence on why. That withdrawal is recorded with its reason.",
```

**P2-3** (`src/probos/cognitive/action_accounting.py`: `withdrawn` keeps its reason for every tag)
SEARCH:
```
#: The reasons of an exit taken before the output was read for blocks: they apply to every tag.
PRE_EXTRACTION = frozenset({"think_failed", "no_output", "no_response", "raw_intent_json"})
```
REPLACE:
```
#: The reasons of an exit taken before the output was read for blocks, and of a withdrawal (BF-976, #1807: the model's ``[WITHDRAWN]`` line covers each action
#: the output did not carry out): they apply to every tag.
PRE_EXTRACTION = frozenset({"think_failed", "no_output", "no_response", "raw_intent_json", "withdrawn"})
```

**P2-4** (`unaccounted` takes the withdrawal text)
SEARCH:
```
def unaccounted(intended: Iterable[object], executed: Sequence[Mapping[str, Any]], reason: str) -> list[dict[str, Any]]:
    """The drop entry of each intended action that nothing in *executed* carried out.
```
REPLACE:
```
def unaccounted(
    intended: Iterable[object], executed: Sequence[Mapping[str, Any]], reason: str, *, withdrawal: str | None = None,
) -> list[dict[str, Any]]:
    """The drop entry of each intended action that nothing in *executed* carried out.

    BF-976 (#1807): a drop whose reason is ``withdrawn`` also carries *withdrawal*, the model's reason as ``action_billets.withdrawal_reason`` reads it: one line of
    at most 200 printable code points, so at most 800 bytes as the governed reader measures a row (UTF-8: 4 bytes for a code point outside the BMP, 2 for a quote
    or a backslash) and at most 2400 bytes as ``EventLog.log`` stores it (ASCII escapes: 12 bytes for a code point outside the BMP), against the reader's caps of
    512 characters a string and 4096 bytes a row. The text goes into the row's ``data`` only, not into its ``detail`` or the log line.
```

**P2-5** (the withdrawal text joins a withdrawn drop)
SEARCH:
```
                if spec.suppressed == "notebook_suppressed":
                    drop["by_design"] = True  # AD-550's dedup and AD-552's repetition gate: counted, and only noted
                break
        drops.append(drop)
```
REPLACE:
```
                if spec.suppressed == "notebook_suppressed":
                    drop["by_design"] = True  # AD-550's dedup and AD-552's repetition gate: counted, and only noted
                break
        if drop["reason"] == "withdrawn" and withdrawal is not None:
            drop["withdrawal"] = withdrawal  # BF-976: the model's reason; a suppression's own reason above carries none
        drops.append(drop)
```

**P2-6** (`settle_intended_actions`: the keyword, and INFO for a withdrawal)
SEARCH:
```
async def settle_intended_actions(
    runtime: Any, agent: Any, intent_id: str, metadata: object, executed: Sequence[Mapping[str, Any]], reason: str,
) -> list[dict[str, Any]]:
```
REPLACE:
```
async def settle_intended_actions(
    runtime: Any, agent: Any, intent_id: str, metadata: object, executed: Sequence[Mapping[str, Any]], reason: str,
    *, withdrawal: str | None = None,
) -> list[dict[str, Any]]:
```
SEARCH:
```
    account for. A drop of ``ward_room_post`` (the usual quality gates) or a by-design notebook suppression is logged at INFO; any other drop is a lost decision and
    is logged at WARNING. Nothing here raises.
    """
    intended = metadata.get("intended_actions") if isinstance(metadata, dict) else None
    if not isinstance(intended, list):
        return []
    drops = unaccounted(intended, executed, reason)
    agent_type = getattr(agent, "agent_type", "")
    callsign = getattr(agent, "callsign", "") or agent_type
    log = getattr(runtime, "event_log", None)
    for drop in drops:
        level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") else logging.WARNING
```
REPLACE:
```
    account for. A drop of ``ward_room_post`` (the usual quality gates), a by-design notebook suppression or a withdrawal (BF-976: the model judged the action
    unsupported and said why, *withdrawal*) is logged at INFO; any other drop is a lost decision and is logged at WARNING. Nothing here raises.
    """
    intended = metadata.get("intended_actions") if isinstance(metadata, dict) else None
    if not isinstance(intended, list):
        return []
    drops = unaccounted(intended, executed, reason, withdrawal=withdrawal)
    agent_type = getattr(agent, "agent_type", "")
    callsign = getattr(agent, "callsign", "") or agent_type
    log = getattr(runtime, "event_log", None)
    for drop in drops:
        level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") or drop["reason"] == "withdrawn" else logging.WARNING
```

**P2-7** (`src/probos/proactive.py`: the import)
SEARCH:
```
from probos.cognitive.action_accounting import settle_intended_actions  # BF-934
from probos.cognitive.proposal_block import PROPOSAL_PATTERN, parse_proposal_block  # BF-934
```
REPLACE:
```
from probos.cognitive.action_accounting import settle_intended_actions  # BF-934
from probos.cognitive.action_billets import withdrawal_reason  # BF-976
from probos.cognitive.proposal_block import PROPOSAL_PATTERN, parse_proposal_block  # BF-934
```

**P2-8** (the silence gate reads the line)
SEARCH:
```
        response_text = sanitize_ward_room_text(response_text)
        # BF-934: a withdrawn observation that still carries a valid block is not silence.
        if not response_text or ("[NO_RESPONSE]" in response_text and not carries_actionable_block(response_text)):
```
REPLACE:
```
        response_text = sanitize_ward_room_text(response_text)
        # BF-934: a withdrawn observation that still carries a valid block is not silence. BF-976 (#1807): a [WITHDRAWN] line withdraws the
        # observation as [NO_RESPONSE] does, with or without the token, so that its reason is recorded and not posted.
        _withdrawal = withdrawal_reason(response_text)
        _silenced = "[NO_RESPONSE]" in response_text or _withdrawal is not None
        if not response_text or (_silenced and not carries_actionable_block(response_text)):
```

**P2-9** (the pure-silence settle, and `_withdrawn`)
SEARCH:
```
            self._circuit_breaker.record_event(agent.id, "no_response", "")
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), [], "no_response")
            return

        _withdrawn = "[NO_RESPONSE]" in response_text  # BF-934: true only when the output carries a valid block (the gate above); see below
```
REPLACE:
```
            self._circuit_breaker.record_event(agent.id, "no_response", "")
            await settle_intended_actions(
                self._runtime, agent, intent.id, getattr(result, "metadata", None), [],
                "withdrawn" if _withdrawal is not None else "no_response", withdrawal=_withdrawal,
            )
            return

        _withdrawn = _silenced  # BF-934: true only when the output carries a valid block (the gate above); see below. BF-976: or a [WITHDRAWN] line
```

**P2-10** (the settle after extraction)
SEARCH:
```
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "no_response" if _withdrawn else "empty_after_extraction")
            return
```
REPLACE:
```
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            _settle_reason = "withdrawn" if _withdrawal is not None else ("no_response" if _withdrawn else "empty_after_extraction")
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, _settle_reason, withdrawal=_withdrawal)
            return
```

**P2-11** (`tests/test_bf976_withdrawal_ledger.py`: the marker becomes a no-op)
SEARCH:
```
# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1807: a withdrawal is recorded as no_response until M2")
```
REPLACE:
```
def built(func):
    """The built cases failed on the base at their own assert and pass now; the marker is a no-op."""
    return func
```

### 6.3 M3: trackers

**P3-1** (`PROGRESS.md`: entry under the title; other batches also insert here, and whichever is applied last sits on top)
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**A proactive think records a judged withdrawal apart from a lost action, with the model's reason (2026-11-17), #1807.**
- **Base.** The single call's billet told a model that judged a decided proposal or notebook entry unsupported to answer [NO_RESPONSE], the same output as a decision it forgot, so the intended-actions ledger recorded both as no_response. A [WITHDRAWN] line written without the token was posted: the tag was removed and the reason became the post.
- **Change.** The billet asks for [NO_RESPONSE] and, on the next line, [WITHDRAWN] with one plain sentence on why. One parser in `cognitive/action_billets.py` reads the first such line and cuts its reason to 200 printable code points. The proactive loop treats the line like the token: the observation is not posted, a valid block beside it is still carried out, and each intended action nothing carried out is recorded with reason withdrawn, logged at INFO, with the reason in the dropped row's `data.withdrawal` (not in its detail or the log line). A bare [NO_RESPONSE] still records no_response. A seam test pins that a retried think writes one declared row per attempt under one correlation id and settles once; the live re-measure of #1673 counts the latest declared row. `tests/test_bf976_withdrawal_ledger.py` adds 23 cases. No config field changes; the one new key is optional in a dropped row's data.
- **Limits.** The line is taught to the single call. Where the chain answers, or BF-204 replaces a reason that cites two identifiers the call was not shown, a judged withdrawal still records as no_response, which over-counts loss. A lower-case marker is not read. An observation written beside the marker is not posted. Contract `prompts/withdrawal-reason-ledger.md`, limits L1 to L9.
```

**P3-2** (`DECISIONS.md`: entry directly before the next entry after the ledger slice, found by its heading text)
SEARCH:
```markdown
### BF-936 -- The standing orders say what crew can do about code changes (2026-11-12, #1677)
```
REPLACE:
```markdown
### A judged withdrawal is recorded apart from a lost action, with its reason, and a retried think settles once (2026-11-17, #1807)

- *Scope.* `cognitive/action_billets.py` (the marker, the cap, `withdrawal_reason`, the billet's clause), `cognitive/action_accounting.py` (`withdrawn` in `PRE_EXTRACTION`; a keyword `withdrawal` on `unaccounted` and `settle_intended_actions`; INFO for a withdrawal), `proactive.py` (the silence gate and the two settles that follow it). One new test file. No config, event type or schema change. Contract `prompts/withdrawal-reason-ledger.md`.
- *G1 (syntax).* [NO_RESPONSE] and then a [WITHDRAWN] line. Rejected: a new silence token, which each reader of [NO_RESPONSE] would need to learn.
- *G2 (the loop).* The line silences an output as the token does, with or without the token. Both silence settles record withdrawn when the line is present; at the second, a valid block beside it is carried out first. The reason goes into the dropped row's data, cut to 200 printable code points (at most 800 bytes under the governed reader's measure).
- *G3 (retries).* No change to the writes; each attempt's triage writes its declared row, and the last attempt settles. The re-measure counts the latest declared row per agent and correlation id. Rejected: settling a superseded attempt, which may carry no metadata.
- *Residual.* The chain's rewriters (COMPOSE's silent path, BF-206, REFLECT's suppress) and BF-204's grounding rule can reduce a withdrawal to the bare token, which records no_response. *Reversal.* Revert the commits of #1807; a dropped row's `withdrawal` key is optional.

### BF-936 -- The standing orders say what crew can do about code changes (2026-11-12, #1677)
```

The orchestrator runs the ledger generator and appends a `*Mutation campaign of record.*` bullet to this entry after section 8.3.

**P3-3** (`prompts/bf-934-dropped-crew-proposals.md`: dated note under D2)
SEARCH:
```markdown
### D2. Make loss visible (acceptance 3, and the crew's reconciliation spec)
```
REPLACE:
```markdown
### D2. Make loss visible (acceptance 3, and the crew's reconciliation spec)

**Note (2026-11-17, #1807).** A later change adds the reason `withdrawn` to the list of reasons below and to `PRE_EXTRACTION`: a single-call output that carries a `[WITHDRAWN] <reason>` line records each intended action nothing carried out as `withdrawn`, with the reason in the row's `data.withdrawal`. It also rewords the billet's withdrawal sentence. Mutation row 46 and L15 are left as this contract's record of the tree it built; `PRE_EXTRACTION` and the billet's length on later trees differ from them. See `prompts/withdrawal-reason-ledger.md`.
```

### 6.4 R2: review round 1's repair of finding F1

Review round 1 found that a `[WITHDRAWN]` marker inside a proposal or notebook block was read as a withdrawal (finding F1; D8 and L7 say what the repair decides). The orchestrator applied the pairs below, in order, to the tree of M3 and R1 (the Builder does not run them): the first four change `proactive.py` and the test file, the last four `PROGRESS.md` and `DECISIONS.md`. The corrections to this contract's own text (the header and sections 2, 3, 4, 5, 8.2, 8.3, 9, 11 and 13) are not pairs here, and the ledger pair is regenerated afterwards. R3 replaces R1's campaign bullet in `DECISIONS.md` with the one for 20 rows.

**R2-S1** (`src/probos/proactive.py`: the helper that reads the line outside the proposal and notebook blocks, after `carries_actionable_block`)
SEARCH:
```
    return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])
```
REPLACE:
```
    return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])


def withdrawal_outside_blocks(text: str) -> str | None:
    """BF-976 (#1807): the reason of the first ``[WITHDRAWN]`` line in *text* outside its notebook and proposal blocks, or None.

    A marker inside one of those blocks is that block's own text and is carried out with it, as it was before the line existed: only a line the model wrote outside
    them withdraws the observation. The blocks come out as the extractor takes them out: the notebook blocks, then every strict proposal block, filed or refused."""
    return withdrawal_reason(re.sub(PROPOSAL_PATTERN, "", split_notebook_blocks(text)[0], flags=re.DOTALL))
```

**R2-S2** (`src/probos/proactive.py`: the silence gate reads the line outside those blocks)
SEARCH:
```
        # BF-934: a withdrawn observation that still carries a valid block is not silence. BF-976 (#1807): a [WITHDRAWN] line withdraws the
        # observation as [NO_RESPONSE] does, with or without the token, so that its reason is recorded and not posted.
        _withdrawal = withdrawal_reason(response_text)
```
REPLACE:
```
        # BF-934: a withdrawn observation that still carries a valid block is not silence. BF-976 (#1807): a [WITHDRAWN] line outside those blocks withdraws the
        # observation as [NO_RESPONSE] does, with or without the token, so that its reason is recorded and not posted; inside one it is that block's own text.
        _withdrawal = withdrawal_outside_blocks(response_text)
```

**R2-T1** (`tests/test_bf976_withdrawal_ledger.py`: the two constants of the new case)
SEARCH:
```
EMOJI = "\U0001F600"  # a code point outside the BMP: 4 bytes in UTF-8, 12 as a JSON ASCII escape
```
REPLACE:
```
EMOJI = "\U0001F600"  # a code point outside the BMP: 4 bytes in UTF-8, 12 as a JSON ASCII escape
NOTEBOOK = "[NOTEBOOK roster-cache]\nRoster reads repeat: read 40 times per cycle.\n[/NOTEBOOK]"
MARKER = "[WITHDRAWN] evidence changed"
```

**R2-T2** (`tests/test_bf976_withdrawal_ledger.py`: case b9, after b8)
SEARCH:
```
    assert "That withdrawal is recorded with its reason." in billet and "answer exactly [NO_RESPONSE]; that withdrawal is recorded." not in billet
```
REPLACE:
```
    assert "That withdrawal is recorded with its reason." in billet and "answer exactly [NO_RESPONSE]; that withdrawal is recorded." not in billet


@built
@pytest.mark.parametrize("reply, expected_threads, expected_drops", [
    (PROPOSAL.replace("Cache the roster", MARKER), ["[Proposal] [WITHDRAWN] evidence changed"], [("notebook", "no_block_executed", None)]),
    (PROPOSAL.replace("per cycle.", f"per cycle.\n{MARKER}"), ["[Proposal] Cache the roster"], [("notebook", "no_block_executed", None)]),
    (NOTEBOOK.replace("per cycle.", f"per cycle.\n{MARKER}"), [], [("proposal", "no_block_executed", None)]),
    (f"[PROPOSAL]\nRationale: The roster is read forty times per cycle.\n{MARKER}\n[/PROPOSAL]", [], [("proposal", "missing_title", None), ("notebook", "no_block_executed", None)]),
    ("Roster reads repeat.\n" + PROPOSAL.replace("Cache the roster", MARKER), ["[Observation] Roster reads repeat.", "[Proposal] [WITHDRAWN] evidence changed"], [("notebook", "no_block_executed", None)]),
    (PROPOSAL.replace("Cache the roster", MARKER) + "\n[WITHDRAWN] the notebook entry can wait", ["[Proposal] [WITHDRAWN] evidence changed"], [("notebook", "withdrawn", "the notebook entry can wait")]),
    (PROPOSAL.replace("[PROPOSAL]\n", "[PROPOSAL] ").replace("per cycle.", f"per cycle.\n{MARKER}"), [], [("proposal", "withdrawn", "evidence changed"), ("notebook", "withdrawn", "evidence changed")]),
], ids=["in-title", "in-rationale", "in-notebook", "refused-block", "with-observation", "inside-and-beside", "unmatched-block"])
async def test_a_marker_inside_a_proposal_or_notebook_block_is_that_blocks_own_text(tmp_path, reply, expected_threads, expected_drops):
    """Review round 1, F1. A marker inside a strict proposal block (filed or refused) or a notebook block withdraws nothing: the block is carried out as written, the
    observation beside it is judged as before and an action nothing carried out is lost, not withdrawn. A marker beside the blocks still decides (inside-and-beside),
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). Rows R17, R18, R19 and R20."""
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, reply, {"intended_actions": ["proposal", "notebook"]}))
        assert sorted(await threads(w)) == sorted(expected_threads)
        assert _drops(await _rows(w, "dropped")) == expected_drops
```

**R2-D1a** (`PROGRESS.md`: the entry says where the loop reads the line)
SEARCH:
```
A bare [NO_RESPONSE] still records no_response. A seam test pins that a retried think
```
REPLACE:
```
A bare [NO_RESPONSE] still records no_response. The loop reads the line outside the proposal and notebook blocks: a marker inside one is that block's own text and withdraws nothing. A seam test pins that a retried think
```

**R2-D1b** (`PROGRESS.md`: the case count)
SEARCH:
```
`tests/test_bf976_withdrawal_ledger.py` adds 23 cases.
```
REPLACE:
```
`tests/test_bf976_withdrawal_ledger.py` adds 30 cases.
```

**R2-D2a** (`DECISIONS.md`: the entry's scope names the helper)
SEARCH:
```
`proactive.py` (the silence gate and the two settles that follow it). One new test file.
```
REPLACE:
```
`proactive.py` (`withdrawal_outside_blocks`, the silence gate and the two settles that follow it). One new test file.
```

**R2-D2b** (`DECISIONS.md`: G2 says where the loop reads the line)
SEARCH:
```
- *G2 (the loop).* The line silences an output as the token does, with or without the token. Both silence settles record withdrawn
```
REPLACE:
```
- *G2 (the loop).* The line silences an output as the token does, with or without the token, and the loop reads it outside the output's proposal and notebook blocks: a marker inside one is that block's own text (review round 1; rejected: stripping every marker line before the extractor reads the output, which would refuse a proposal whose title holds the marker). Both silence settles record withdrawn
```

### 6.5 R4: what R2 said of its case b9

On the base, the test file of R2 gives 23 failures and 7 passes: five of b9's seven cases pass there, because they pin what the base does with a marker inside a block (they fail on M2 as built), so b9 is not a `built` case. The orchestrator applied the pairs below to the tree of R3. Nothing but the marker and the docstrings changes in the test file: the cases, the source and the table of 8.3 are as in R2. R5 replaces R3's campaign bullet in `DECISIONS.md`, because the test file's bytes changed.

**R4-T1** (`tests/test_bf976_withdrawal_ledger.py`: the module's docstring says that b9 is neither a built case nor a control)
SEARCH:
```
text with the ``intended_actions`` metadata the lifecycle would attach. The ``built`` cases fail on the base at their own assert; the two controls pass on both.
```
REPLACE:
```
text with the ``intended_actions`` metadata the lifecycle would attach. The ``built`` cases fail on the base at their own assert; the two controls pass on both.
b9, which R2 added, is neither: its docstring says which of its cases pass on the base.
```

**R4-T2** (`tests/test_bf976_withdrawal_ledger.py`: b9 is not marked `built`)
SEARCH:
```
@built
@pytest.mark.parametrize("reply, expected_threads, expected_drops", [
```
REPLACE:
```
@pytest.mark.parametrize("reply, expected_threads, expected_drops", [
```

**R4-T3** (`tests/test_bf976_withdrawal_ledger.py`: b9's docstring says which cases pass on the base and on M2)
SEARCH:
```
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). Rows R17, R18, R19 and R20."""
```
REPLACE:
```
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). On the base the first five cases pass (they pin what the base does, which M2
    as built changed) and the last two fail; on M2 as built unmatched-block passes and the other six fail. Rows R17, R18, R19 and R20."""
```

### 6.6 R7: review round 2's repair of finding F2

Review round 2 found that removing a block with nothing in its place joined its neighbours: `[WITH`, a block and `DRAWN]` read as a marker that the model never wrote, and a reason could run on past a removed block (finding F2; D8 and L7 say what the repair decides). The repair puts a line break in place of each removed block. The orchestrator applied the pairs below, in order, to the tree of R6: the first three change `proactive.py` and the test file, the last two `PROGRESS.md` and `DECISIONS.md`. The corrections to this contract's own text (the header, D8, L7 and sections 4, 8.2, 8.3, 9 and 13) are not pairs here, and the ledger pair is regenerated afterwards. R8 (6.7) replaces the helper that R7-S1 writes, and R9 replaces R5's campaign bullet in `DECISIONS.md` with the one for 25 rows.

**R7-S1** (`src/probos/proactive.py`: each removed block leaves a line break, so no marker forms across it and no reason runs on past it)
SEARCH:
```
    A marker inside one of those blocks is that block's own text and is carried out with it, as it was before the line existed: only a line the model wrote outside
    them withdraws the observation. The blocks come out as the extractor takes them out: the notebook blocks, then every strict proposal block, filed or refused."""
    return withdrawal_reason(re.sub(PROPOSAL_PATTERN, "", split_notebook_blocks(text)[0], flags=re.DOTALL))
```
REPLACE:
```
    A marker inside one of those blocks is that block's own text and is carried out with it, as it was before the line existed: only a line the model wrote outside
    them withdraws the observation. The blocks come out with the patterns the extractor takes them out with: the notebook blocks, then every strict proposal block,
    filed or refused (it also removes ``[READ_NOTEBOOK]`` tags and ``[NOTE]`` blocks between the two, which this does not). Each comes out as a line break, so that
    no marker forms across a removed block and no reason runs on past one."""
    return withdrawal_reason(re.sub(PROPOSAL_PATTERN, "\n", _NOTEBOOK_PATTERN.sub("\n", text), flags=re.DOTALL))
```

**R7-T1** (`tests/test_bf976_withdrawal_ledger.py`: three more parameters of b9)
SEARCH:
```
], ids=["in-title", "in-rationale", "in-notebook", "refused-block", "with-observation", "inside-and-beside", "unmatched-block"])
```
REPLACE:
```
    ("[WITH" + PROPOSAL + "DRAWN] evidence changed", ["[Observation] evidence changed", "[Proposal] Cache the roster"], [("notebook", "no_block_executed", None)]),
    ("[WITH" + NOTEBOOK + "DRAWN] evidence changed", ["[Observation] evidence changed"], [("proposal", "no_block_executed", None)]),
    ("[WITHDRAWN] first part " + PROPOSAL + " trailing text", ["[Proposal] Cache the roster"], [("notebook", "withdrawn", "first part")]),
], ids=["in-title", "in-rationale", "in-notebook", "refused-block", "with-observation", "inside-and-beside", "unmatched-block", "split-by-proposal", "split-by-notebook", "reason-before-block"])
```

**R7-T2** (`tests/test_bf976_withdrawal_ledger.py`: b9's docstring says what the three new cases pin and which cases pass on the base)
SEARCH:
```
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). On the base the first five cases pass (they pin what the base does, which M2
    as built changed) and the last two fail; on M2 as built unmatched-block passes and the other six fail. Rows R17, R18, R19 and R20."""
```
REPLACE:
```
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). Removing a block leaves a line break, so that a marker the model did not write
    does not form across it (split-by-proposal, split-by-notebook) and a reason ends where a removed block begins (reason-before-block). On the base every case passes except
    inside-and-beside, unmatched-block and reason-before-block, which need the withdrawal line; the others pin what the base does. On the tree of R6, which joined the text
    around a removed block, the last three fail. Rows R17 to R22."""
```

**R7-D1** (`PROGRESS.md`: the case count)
SEARCH:
```
`tests/test_bf976_withdrawal_ledger.py` adds 30 cases.
```
REPLACE:
```
`tests/test_bf976_withdrawal_ledger.py` adds 33 cases.
```

**R7-D2** (`DECISIONS.md`: G2 says that a removed block leaves a line break)
SEARCH:
```
(review round 1; rejected: stripping every marker line before the extractor reads the output
```
REPLACE:
```
(review rounds 1 and 2: each removed block leaves a line break, so that no marker forms across it; rejected: stripping every marker line before the extractor reads the output
```

### 6.7 R8: the orchestrator's repair of R7's helper before review round 3

The orchestrator compared the helper of R7 with the extractor's own stripping (the extractor removes each block with nothing in its place, so it sees the text joined) over every sequence of up to seven pieces of the block vocabulary. The line break that R7 put in place of each removed block made a strict closer that the joined text lacks (a marker outside any block was hidden) and closed a block early that the joined text closes later (a marker inside one was read); D8 and L7 say what the repair decides. The repair puts a form feed in place of each removed block while the blocks are found and a line break only for the parser, and reads a form feed in the text itself as a space. The orchestrator applied the pairs below, in order, to the tree of R7: the first three change `proactive.py` and the test file, the last two `PROGRESS.md` and `DECISIONS.md`. The corrections to this contract's own text (the header, D8, L7 and sections 4, 6.6, 8.2, 8.3, 9 and 13) are not pairs here, and the ledger pair is regenerated afterwards. R9 replaces R5's campaign bullet in `DECISIONS.md` with the one for 25 rows.

**R8-S1** (`src/probos/proactive.py`: a removed block is a form feed while the blocks are found and a line break only for the parser, so that no strict closer is made or lost)
SEARCH:
```
    An output that withdraws the observation with ``[NO_RESPONSE]`` but still carries one is read for its blocks, not discarded as silence."""
    return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])


def withdrawal_outside_blocks(text: str) -> str | None:
    """BF-976 (#1807): the reason of the first ``[WITHDRAWN]`` line in *text* outside its notebook and proposal blocks, or None.

    A marker inside one of those blocks is that block's own text and is carried out with it, as it was before the line existed: only a line the model wrote outside
    them withdraws the observation. The blocks come out with the patterns the extractor takes them out with: the notebook blocks, then every strict proposal block,
    filed or refused (it also removes ``[READ_NOTEBOOK]`` tags and ``[NOTE]`` blocks between the two, which this does not). Each comes out as a line break, so that
    no marker forms across a removed block and no reason runs on past one."""
    return withdrawal_reason(re.sub(PROPOSAL_PATTERN, "\n", _NOTEBOOK_PATTERN.sub("\n", text), flags=re.DOTALL))
```
REPLACE:
```
    An output that withdraws the observation with ``[NO_RESPONSE]`` but still carries one is read for its blocks, not discarded as silence."""
    return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])


_BLOCK_BREAK = "\f"  # whitespace, not a line break: what a removed block leaves while the blocks are found (withdrawal_outside_blocks)


def withdrawal_outside_blocks(text: str) -> str | None:
    """BF-976 (#1807): the reason of the first ``[WITHDRAWN]`` line in *text* outside its notebook and proposal blocks, or None.

    A marker inside one of those blocks is that block's own text and is carried out with it, as it was before the line existed: only a line the model wrote outside
    them withdraws the observation. The blocks come out with the patterns the extractor takes them out with: the notebook blocks, then every strict proposal block,
    filed or refused (it also removes ``[READ_NOTEBOOK]`` tags and ``[NOTE]`` blocks between the two, which this does not). The extractor joins the text around a removed
    notebook block, so while the blocks are found each removed block is a form feed: whitespace, which the proposal pattern passes over as it passes over the join, and not
    a line break, which could close a block early or make a closer that the joined text lacks. Then each becomes a line break for the parser, so that no marker forms across
    a removed block and no reason runs on past one. A form feed in the text itself is a space first, as the parser reads it. A proposal tag that only the removal of a
    notebook block completes is one the extractor finds and this does not (contract L7)."""
    view = re.sub(PROPOSAL_PATTERN, _BLOCK_BREAK, _NOTEBOOK_PATTERN.sub(_BLOCK_BREAK, text.replace(_BLOCK_BREAK, " ")), flags=re.DOTALL)
    return withdrawal_reason(view.replace(_BLOCK_BREAK, "\n"))
```

**R8-T1** (`tests/test_bf976_withdrawal_ledger.py`: three more parameters of b9)
SEARCH:
```
    ("[WITHDRAWN] first part " + PROPOSAL + " trailing text", ["[Proposal] Cache the roster"], [("notebook", "withdrawn", "first part")]),
], ids=["in-title", "in-rationale", "in-notebook", "refused-block", "with-observation", "inside-and-beside", "unmatched-block", "split-by-proposal", "split-by-notebook", "reason-before-block"])
```
REPLACE:
```
    ("[WITHDRAWN] first part " + PROPOSAL + " trailing text", ["[Proposal] Cache the roster"], [("notebook", "withdrawn", "first part")]),
    (f"[PROPOSAL]\nTitle: Cache the roster\n{MARKER}{NOTEBOOK}[/PROPOSAL]", [], [("proposal", "malformed_block", None)]),
    (f"Roster reads repeat.\n[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.{NOTEBOOK}[/PROPOSAL]\nAffected Systems: Ward Room\n{MARKER}\n[/PROPOSAL]",
     ["[Observation] Roster reads repeat.", "[Proposal] Cache the roster"], []),
    ("[WITHDRAWN] first\x0csecond", [], [("proposal", "withdrawn", "first second"), ("notebook", "withdrawn", "first second")]),
], ids=["in-title", "in-rationale", "in-notebook", "refused-block", "with-observation", "inside-and-beside", "unmatched-block", "split-by-proposal", "split-by-notebook", "reason-before-block",
        "closer-after-notebook", "early-closer-after-notebook", "form-feed-in-reason"])
```

**R8-T2** (`tests/test_bf976_withdrawal_ledger.py`: b9's docstring says what the three new cases pin and which cases pass on the base)
SEARCH:
```
    """Review round 1, F1. A marker inside a strict proposal block (filed or refused) or a notebook block withdraws nothing: the block is carried out as written, the
    observation beside it is judged as before and an action nothing carried out is lost, not withdrawn. A marker beside the blocks still decides (inside-and-beside),
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). Removing a block leaves a line break, so that a marker the model did not write
    does not form across it (split-by-proposal, split-by-notebook) and a reason ends where a removed block begins (reason-before-block). On the base every case passes except
    inside-and-beside, unmatched-block and reason-before-block, which need the withdrawal line; the others pin what the base does. On the tree of R6, which joined the text
    around a removed block, the last three fail. Rows R17 to R22."""
```
REPLACE:
```
    """Review rounds 1 and 2, F1 and F2. A marker inside a strict proposal block (filed or refused) or a notebook block withdraws nothing: the block is carried out as written,
    the observation beside it is judged as before and an action nothing carried out is lost, not withdrawn. A marker beside the blocks still decides (inside-and-beside),
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). A removed block reaches the parser as a line break, so that a marker the model did
    not write does not form across it (split-by-proposal, split-by-notebook) and a reason ends where a removed block begins (reason-before-block). While the blocks are found it
    is a form feed, because the extractor joins the text around a removed notebook block and a line break there made a closer that the joined text lacks (closer-after-notebook:
    the marker is outside any block, so the reply withdraws) and closed a block early that the joined text closes later (early-closer-after-notebook: the marker is inside it,
    so the observation is posted). A form feed that the model wrote is a space, as the parser reads it (form-feed-in-reason). On the base every case passes except inside-and-beside,
    unmatched-block, reason-before-block, closer-after-notebook and form-feed-in-reason, which need the withdrawal line; the others pin what the base does. On the tree of R6,
    which joined the text around a removed block, split-by-proposal, split-by-notebook and reason-before-block fail; on the tree of R7, which left a line break,
    closer-after-notebook and early-closer-after-notebook fail. Rows R17 to R25."""
```

**R8-D1** (`PROGRESS.md`: the case count)
SEARCH:
```
`tests/test_bf976_withdrawal_ledger.py` adds 33 cases.
```
REPLACE:
```
`tests/test_bf976_withdrawal_ledger.py` adds 36 cases.
```

**R8-D2** (`DECISIONS.md`: G2 says what a removed block is while the blocks are found)
SEARCH:
```
(review rounds 1 and 2: each removed block leaves a line break, so that no marker forms across it; rejected: stripping every marker line before the extractor reads the output
```
REPLACE:
```
(review rounds 1 and 2 and the orchestrator's own check: while the blocks are found each removed block is a form feed, so that none makes a strict closer or ends a block early that the extractor, which joins the text around it, does not, and for the parser it is a line break, so that no marker forms across it; rejected: stripping every marker line before the extractor reads the output
```

## 7. Builder: may and may not

- **May:** apply the pairs in order; run `git diff --check` and `git diff --stat`; commit as section 4 says.
- **May not:** run tests; edit any file not named here, in particular `cognitive_agent.py`, `sub_tasks/compose.py`, `sub_tasks/reflect.py` or `output_grounding.py`; change mutation row 46 or L15 of the BF-934 contract; add a config field; add `skip`, `xfail` (other than M1's marker) or a retry; reword a SEARCH anchor.

## 8. Gates (the orchestrator runs them; set `PROBOS_EMBEDDINGS=local`)

### 8.1 Base counts, before M1

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf934_s1_decision_routing.py tests/test_bf934_s2_secondary_gates.py tests/test_bf934_s3_intended_actions_ledger.py tests/test_combo_a_ad576b_retry.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_bf922_fallback_gate.py tests/test_bf922_output_grounding.py tests/test_proactive.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
```

Record each file's count. I did not run these.

### 8.2 Checks

- After M1: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf976_withdrawal_ledger.py -n 0 -p no:randomly -q`. Expected: `2 passed, 21 xfailed`.
- After M2: the 8.1 command with `tests/test_bf976_withdrawal_ledger.py` added. Expected: 23 passed for the new file, and every other file at its base count, all passed.
- After R2: the same command. Expected: 30 passed for the new file (M2's 23 and the seven of b9), and every other file at its base count, all passed.
- After R7: the same command. Expected: 33 passed for the new file (M2's 23 and the ten of b9), and every other file at its base count, all passed.
- After R8: the same command. Expected: 36 passed for the new file (M2's 23 and the thirteen of b9), and every other file at its base count, all passed.
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check` both pass.
- After M3: the ledger generator, then `tests/test_ad1184_ad_ledger.py`.

### 8.3 Mutation campaign (one row at a time on the R8 tree, restored before the next)

Each original occurs once in its file, as a substring of one line. "At least" marks a row whose mutant may break more cases than the ones listed.

| Row | File | Original | Mutant | Killed by |
|---|---|---|---|---|
| R1 | action_billets.py | `start = text.find(WITHDRAWN_MARKER)` | `start = text.rfind(WITHDRAWN_MARKER)` | b5[first reason] |
| R2 | action_billets.py | `if start < 0:` | `if start < -1:` | at least b5[`[NO_RESPONSE]`], b5[""], b5[lower case], c1 |
| R3 | action_billets.py | `rest = text[start + len(WITHDRAWN_MARKER):].split("\n", 1)[0]` | `rest = text[start + len(WITHDRAWN_MARKER):]` | at least b5[next line], b5[first reason], b9[unmatched-block], b9[reason-before-block] |
| R4 | action_billets.py | `cleaned = "".join(ch if ch.isprintable() else " " for ch in rest)` | `cleaned = rest` | at least b5[next line] |
| R5 | action_billets.py | `return " ".join(cleaned.split())[:WITHDRAWAL_REASON_CHARS].rstrip()` | `return " ".join(cleaned.split())` | b6 (both), b7 |
| R6 | action_billets.py | `f"[NO_RESPONSE] on one line and, on the next, {WITHDRAWN_MARKER} followed by one plain sentence on why. That withdrawal is recorded with its reason.",` | `"[NO_RESPONSE]; that withdrawal is recorded.",` | b8, b1 |
| R7 | action_accounting.py | `PRE_EXTRACTION = frozenset({"think_failed", "no_output", "no_response", "raw_intent_json", "withdrawn"})` | the same without `, "withdrawn"` | b1, b2 (4), b3 (2), b4, b7, b9[inside-and-beside], b9[unmatched-block], b9[reason-before-block], b9[form-feed-in-reason] |
| R8 | action_accounting.py | `if drop["reason"] == "withdrawn" and withdrawal is not None:` | `if False:` | b1, b2 (4), b3 (2), b7, b9[inside-and-beside], b9[unmatched-block], b9[reason-before-block], b9[form-feed-in-reason] |
| R9 | action_accounting.py | `drops = unaccounted(intended, executed, reason, withdrawal=withdrawal)` | `drops = unaccounted(intended, executed, reason)` | b1, b2 (4), b3 (2), b7, b9[inside-and-beside], b9[unmatched-block], b9[reason-before-block], b9[form-feed-in-reason] |
| R10 | action_accounting.py | `level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") or drop["reason"] == "withdrawn" else logging.WARNING` | the same without `or drop["reason"] == "withdrawn" ` | b4 |
| R11 | proactive.py | `"withdrawn" if _withdrawal is not None else "no_response", withdrawal=_withdrawal,` | `"no_response", withdrawal=_withdrawal,` (the issue's mutation) | b1, b2 (4), b4, b9[unmatched-block], b9[form-feed-in-reason] |
| R12 | proactive.py | `_withdrawal = withdrawal_outside_blocks(response_text)` | `_withdrawal = ""` | at least c1 |
| R13 | proactive.py | `_silenced = "[NO_RESPONSE]" in response_text or _withdrawal is not None` | `_silenced = "[NO_RESPONSE]" in response_text` | b2[`[WITHDRAWN] evidence changed`], b2[observation], b3[""], b9[inside-and-beside], b9[unmatched-block], b9[reason-before-block], b9[closer-after-notebook], b9[form-feed-in-reason] |
| R14 | proactive.py | `_withdrawn = _silenced  #` | `_withdrawn = "[NO_RESPONSE]" in response_text  #` | b3[""], b9[inside-and-beside], b9[reason-before-block], b9[closer-after-notebook] |
| R15 | proactive.py | `_settle_reason = "withdrawn" if _withdrawal is not None else ("no_response" if _withdrawn else "empty_after_extraction")` | `_settle_reason = "no_response" if _withdrawn else "empty_after_extraction"` | b3 (both), b9[inside-and-beside], b9[reason-before-block] |
| R16 | proactive.py | `await asyncio.sleep(_backoff)` | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), [], "think_failed"); await asyncio.sleep(_backoff)` | c2 |
| R17 | proactive.py | `_withdrawal = withdrawal_outside_blocks(response_text)` | `_withdrawal = withdrawal_reason(response_text)` (the loop reads the whole output) | b9[in-title], b9[in-rationale], b9[in-notebook], b9[refused-block], b9[with-observation], b9[inside-and-beside], b9[reason-before-block], b9[early-closer-after-notebook] |
| R18 | proactive.py | `view = re.sub(PROPOSAL_PATTERN, _BLOCK_BREAK, _NOTEBOOK_PATTERN.sub(_BLOCK_BREAK, text.replace(_BLOCK_BREAK, " ")), flags=re.DOTALL)` | `view = _NOTEBOOK_PATTERN.sub(_BLOCK_BREAK, text.replace(_BLOCK_BREAK, " "))` (the helper strips notebook blocks only) | b9[in-title], b9[in-rationale], b9[refused-block], b9[with-observation], b9[inside-and-beside], b9[reason-before-block], b9[early-closer-after-notebook] |
| R19 | proactive.py | the same | `view = re.sub(PROPOSAL_PATTERN, _BLOCK_BREAK, text.replace(_BLOCK_BREAK, " "), flags=re.DOTALL)` (the helper strips proposal blocks only) | b9[in-notebook] |
| R20 | proactive.py | the same | `view = re.sub(r"\[PROPOSAL\].*?\[/PROPOSAL\]", _BLOCK_BREAK, _NOTEBOOK_PATTERN.sub(_BLOCK_BREAK, text.replace(_BLOCK_BREAK, " ")), flags=re.DOTALL)` (a looser pattern than the extractor's) | b9[unmatched-block], b9[closer-after-notebook], b9[early-closer-after-notebook] |
| R21 | proactive.py | the same | `view = re.sub(PROPOSAL_PATTERN, "", _NOTEBOOK_PATTERN.sub(_BLOCK_BREAK, text.replace(_BLOCK_BREAK, " ")), flags=re.DOTALL)` (a removed proposal block leaves nothing) | b9[split-by-proposal], b9[reason-before-block] |
| R22 | proactive.py | the same | `view = re.sub(PROPOSAL_PATTERN, _BLOCK_BREAK, _NOTEBOOK_PATTERN.sub("", text.replace(_BLOCK_BREAK, " ")), flags=re.DOTALL)` (a removed notebook block leaves nothing) | b9[split-by-notebook] |
| R23 | proactive.py | the line of R18 | `view = re.sub(PROPOSAL_PATTERN, "\n", _NOTEBOOK_PATTERN.sub("\n", text.replace(_BLOCK_BREAK, " ")), flags=re.DOTALL)` (a removed block is a line break while the blocks are found: R7's helper) | b9[closer-after-notebook], b9[early-closer-after-notebook] |
| R24 | proactive.py | `return withdrawal_reason(view.replace(_BLOCK_BREAK, "\n"))` | `return withdrawal_reason(view)` (a form feed, not a line break, reaches the parser) | b9[reason-before-block] |
| R25 | proactive.py | the line of R18 | `view = re.sub(PROPOSAL_PATTERN, _BLOCK_BREAK, _NOTEBOOK_PATTERN.sub(_BLOCK_BREAK, text), flags=re.DOTALL)` (a form feed in the text is not made a space first) | b9[form-feed-in-reason] |

Case names: c1, c2 are the two controls in file order. b1 to b8 are the `built` functions in file order, b9 is the case that R2 adds (not `built`), and a bracket names a parameter (b9's are its ids: in-title, in-rationale, in-notebook, refused-block, with-observation, inside-and-beside, unmatched-block, split-by-proposal, split-by-notebook, reason-before-block, closer-after-notebook, early-closer-after-notebook, form-feed-in-reason).

### 8.4 Broad gate

Once for the issue, after review: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label 1807 --receipt logs/gates/1807.receipt.json`.

## 9. Diff Reviewer: properties to verify

1. On the M2 tree, an output with no `[WITHDRAWN]` reaches each settle with the same reason as on the base.
2. No path that leaves a `[WITHDRAWN]` line in `response_text` reaches `_post_to_ward_room`, `_is_similar_to_recent_posts`, the novelty gate or `wm.record_observation`.
3. The model's reason appears only in `data.withdrawal`, not in `detail` or in any log line of `action_accounting.py` or `proactive.py`.
4. `withdrawal_reason` returns `None` or a `str` of at most 200 code points, each with `isprintable()` True, with no leading or trailing whitespace.
5. Every existing call of `settle_intended_actions` and `unaccounted` still type-checks; the new parameter is keyword-only with default `None`.
6. The billet contains no hex-like run and no word taken from the triage; the existing tests in `TestTheBilletRepeatsNoWordOfTheTriage` pass unchanged.
7. After M2, `built` is a no-op and no `skip`, `xfail` or retry remains.
8. A `[WITHDRAWN]` inside a strict proposal block or a notebook block withdraws nothing: the block is carried out and an action nothing carried out records the reason the base records (b9); a marker outside those blocks still decides.
9. No marker is read that the model did not write: removing a block leaves a line break, so `[WITH`, a block and `DRAWN]` read as no marker, and a reason ends where a removed block begins (b9).
10. The helper finds the blocks in the text as the extractor has it: a removed block makes no strict closer that the joined text lacks and ends no block early that the joined text closes later (b9: closer-after-notebook, early-closer-after-notebook), and a form feed in the reply is read as a space (b9: form-feed-in-reason). The one recorded exception is a proposal tag that only the removal of a notebook block completes (L7).

## 10. Verified Against Codebase (2026-11-17, commit `4f10b15f7e5acb08340e46f46ea3adf23d6005d1`)

```
rg -n "that withdrawal is recorded|^BILLET_TAGS|^def decision_billet|^DECISION_HEADING" src/probos/cognitive/action_billets.py
  38: DECISION_HEADING = "Your triage already decided this turn"
  44: BILLET_TAGS = (*_BLOCK_TAGS, *_COMPANION_TAGS)
  47: def decision_billet(intended: Iterable[object] | None) -> str:
  68:         "[NO_RESPONSE]; that withdrawal is recorded.",
rg -n "^PRE_EXTRACTION|^def unaccounted|^async def settle_intended_actions|level = logging.INFO|drops = unaccounted" src/probos/cognitive/action_accounting.py
  52, 69, 117, 134, 129
rg -n "settle_intended_actions|carries_actionable_block|_withdrawn|asyncio.sleep\(_backoff\)|_BACKOFFS_SECONDS =|re.sub\(r'\\\[" src/probos/proactive.py
  44 (import), 240 (def carries_actionable_block), 1402, 1418, 1449, 1460, 1533, 1536, 1547, 1558, 1569, 1581, 1595, 1614, 3680 (the closing-tag strip, re.sub(r'\[/PROPOSAL\]', ...): not BF-203's), 3971
rg -n "_intended_actions\"|^def _actions_lost|^_ACTION_MARKERS|silence included|record_declared\(|_gate_fallback_output" src/probos/cognitive/cognitive_agent.py
  315, 378, 393, 3779, 4737, 4747, 6346, 6503, 6541, 6705, 11550
rg -n "CHAIN_FALLBACK_KEY\] = True" src/probos/cognitive/cognitive_agent.py      -> 3884, 3916
rg -n "MIN_UNGROUNDED_IDS =" src/probos/cognitive/output_grounding.py              -> 31
rg -n "NO_RESPONSE" src/probos/cognitive/sub_tasks/compose.py src/probos/cognitive/sub_tasks/reflect.py
  compose.py:275 (prompt text that forbids the token in a duty cycle), 657 (the silent short-circuit); reflect.py:161, 243, 323 (the "(C) Suppress" option, offered in three prompts), 217 and 232 (prompt text), 409 (the suppress result), 590 (the check that reads that result)
rg -n "BF-206: Defense" src/probos/cognitive/cognitive_agent.py                    -> 6263
rg -n "_MAX_JSON_STRING_CHARS =|_MAX_RAW_DATA_BYTES =|_MAX_SERIALIZED_ROW_BYTES =|ensure_ascii=False|json.dumps\(data" src/probos/substrate/event_log.py
  34, 35, 36, 323, 659
rg -n "^class WardRoomThread|    body: str" src/probos/ward_room/models.py          -> 26, 31
rg -n "\"body\": row\[4\]" src/probos/ward_room/threads.py                       -> 749 (a post's body in get_thread)
rg -n "def world|def crew|def thinker|def threads|^DECIDED" tests/bf934_world.py     -> 38, 119, 180, 193, 220
rg -n "query_governed|EventLogQuerySpec" tests/test_bf934_s3_intended_actions_ledger.py -> 23, 297
rg -n "proactive" docs/development/architecture-baseline.yaml                    -> 862 (lines, methods), 1118
rg -n "_STATUS_PATTERNS|_HEAD_WINDOW = 120" scripts/gen_ad_ledger.py              -> 126-127 (WITHDRAWN, case-insensitive), 139
```

The tracker lines carry no `AD-` or `BF-` head token, so the ledger's head-keyword rule (`gen_ad_ledger.py:127`, which reads "withdrawn" as retired) does not apply to them.

## Absence Verified (2026-11-17)

```
CLAIM: src has no reader of a [WITHDRAWN] marker or a "withdrawn" reason today
RUN:   rg -n 'WITHDRAWN|withdrawal_reason|"withdrawn"' src
FOUND: src/probos/routers/security.py:322 ("withdrawn": result.withdrawn, an unrelated field)
HOLDS: yes

CLAIM: no code reads the declared or dropped rows (#1673's re-measure is a procedure)
RUN:   rg -l -e DECLARED_EVENT -e DROPPED_EVENT -e '"declared"' -e '"intended_actions", event' src scripts tests
FOUND: src/probos/cognitive/action_accounting.py (the writer); src/probos/routers/chat.py:1177 and scripts/check_config_profiles.py:604 (unrelated "declared" keys);
       tests: test_bf934_s3 (the ledger), test_ad1195_eventlog_pair_freeze.py:109-110 (the pairs), and five tests whose "declared" is unrelated
HOLDS: yes

CLAIM: the consumers of the edited names are two test files, the BF-934 contract and the trackers
RUN:   rg -c 'PRE_EXTRACTION|decision_billet|DECISION_HEADING|settle_intended_actions|record_declared|unaccounted\(|that withdrawal is recorded|WITHDRAWN' .
FOUND: 12 files: proactive.py, cognitive_agent.py, action_billets.py, action_accounting.py, scripts/gen_ad_ledger.py (its own keyword list),
       prompts/bf-934-dropped-crew-proposals.md, prompts/ad-1270a-activation-receipts.md and prompts/ad-1270-onboarding.md (ledger keyword text),
       DECISIONS.md, PROGRESS.md, tests/test_bf934_s1_decision_routing.py, tests/test_bf934_s3_intended_actions_ledger.py
HOLDS: yes; rg -l 'action_accounting|action_billets' tests -> the same two test files

CLAIM: no config field concerns a withdrawal
RUN:   rg -l -i withdraw src/probos
FOUND: 10 files, none of them config.py or config_models/
HOLDS: yes
```

## 11. What this does NOT change, and recorded limits

Not changed: COMPOSE, EVALUATE, REFLECT, BF-206, BF-204's gate, `_actions_lost`, `carries_actionable_block`, AD-576b's retry, `record_declared`, the EventLog schema and its pairs, and config.

- **L1.** BF-204 (`output_grounding.py:31`, two ungrounded ids) replaces a reply whose reason cites two hex ids the call was not shown with the bare token. The orchestrator measured this on this tree. The withdrawal then records `no_response`. The billet asks for a plain sentence.
- **L2.** The line is taught to the single call only (`cognitive_agent.py:11550`). In the chain, these emit the bare token, so a judged withdrawal there records `no_response`, which over-counts loss:
  - COMPOSE's silent short-circuit (`compose.py:657`);
  - BF-206 (`cognitive_agent.py:6263`);
  - REFLECT's suppress (`reflect.py:409`) and its "(C) Suppress" option (`reflect.py:161, 243, 323`).
- **L3.** `_actions_lost` (`cognitive_agent.py:393`) keeps an approved output when a rewrite drops an action or silences it (BF-934 G3: "silence included" at `:6705` means that the *rewrite* is silence, as in `tests/test_bf934_s2_secondary_gates.py:209-210`, where the rewrite is the token). It ignores the *original's* silence: the orchestrator's probe returned `[]` for an original that carries the token or the line. A rewrite happens only when the compose text carries a marker the triage did not declare (`:6613`), so a bare token never reaches it. An output that carries the token and such a marker could be rewritten into text that is posted; a valid block beside the token is carried out either way (`tests/test_bf934_s2_secondary_gates.py:181-193`). Not changed here.
- **L4.** At `:1569`, `withdrawn` applies by decision (D4).
- **L5.** A lower-case `[withdrawn]` is not read. BF-203's regex does not remove it either, so it is posted as written.
- **L6.** An observation written beside a token-less marker is not posted (D4).
- **L7.** A `[WITHDRAWN]` inside a strict `[PROPOSAL]` block (filed or refused) or a `[NOTEBOOK]` block is that block's own text: the loop reads the line outside those blocks (D8) and carries the block out as the base does (b9). A marker inside a `[PROPOSAL]` that `PROPOSAL_PATTERN` does not match (one written on a single line, or without a newline after its tag; one with a `[READ_NOTEBOOK]` tag or a `[NOTE]` block between its tag and the newline; and one whose tag or closer is completed only by the removal of a block from inside it, as in `[PROPO`, a notebook block and `SAL]`: the extractor removes those blocks and joins the text around them before it reads the proposal and files it, and the helper removes the notebook blocks and leaves whitespace in their place, which no tag spans, and the other two kinds not at all) or inside any other kind of block is read, and it withdraws the turn as the token does: the observation is not posted, and the extractor runs over the output only when it also carries a valid proposal or notebook block (L4), in which case it carries out every action the output holds, as it does for the token. The orchestrator's probe: with a marker inside a `[NOTE]` block, an unwritten notebook entry records `withdrawn` where the base records `no_block_executed`, and a `[NOTE]` block or a `[READ_NOTEBOOK]` tag with no valid block beside it is no longer carried out. With `[PROPO`, a notebook block and `SAL]` as a proposal that holds a marker, the turn records `withdrawn` where the base records `empty_after_extraction`; the notebook entry, the refused proposal and the Ward Room are the base's (the orchestrator's probe on R8).
- **L8.** Effects on silence handling:
  - A token-less withdrawal now also runs the loop's silence block: the duty record, AD-414's trust signal for disciplined silence (`trust_no_response_weight`, default 0.0: no signal unless configured, `config.py:3218`), AD-430a's no-response episode, which is built and then refused by `EpisodicMemory.should_store` (`cognitive/episodic.py:1955-1957`: a proactive no-response is skipped), so none is stored, and AD-488's `no_response` circuit-breaker event.
  - BF-864's decision cache (off by default) can replay a cached withdrawal.
- **L9.** Retries write one declared row per attempt, by the issue's decision. The re-measure counts the latest (#1673's reopening comment).

## 12. Prior art and blind spots (date used: 2026-11-17)

This is a bug fix in ProbOS-specific plumbing: a reason line in the model's reply and one key on a ledger row. The external search is skipped, per the drafting standard for bug fixes. A structured refusal field in a JSON reply was considered and rejected, because the single call answers free text. Internal sources used:
- the BF-934 contract (D2, L4, L5, row 46, L15);
- #1673's reopening comment (step 5: latest declared row; withdrawn reported apart);
- the orchestrator's probes on this tree.

The blind spots found are L5 to L8 and the ledger keyword rule noted under section 10.

## 13. Acceptance criteria

- `[NO_RESPONSE]\n[WITHDRAWN] evidence changed` after a proposal billet records a dropped row with reason `withdrawn` and `data.withdrawal == "evidence changed"`; a bare `[NO_RESPONSE]` records `no_response` (b1, c1).
- The withdrawal line reaches no Ward Room thread or post, with or without the token (b2, b3).
- A think whose first `handle_intent` returns a transient LLM error after its triage, and whose second succeeds, writes two declared rows with one correlation id and one settlement (c2).
- A `[WITHDRAWN]` inside a proposal or notebook block withdraws nothing: for every action that nothing carried out, the ledger records what it records on the base (b9).
- A reply that holds no `[WITHDRAWN]` records no withdrawal, however its blocks sit: removing a block leaves a line break, so `[WITH`, a block and `DRAWN]` read as no marker (b9).
- The helper finds the blocks as the extractor does, apart from a proposal tag that only the removal of a notebook block completes (L7): a removed block makes no strict closer and ends no block early, and a form feed that the model wrote is read as a space (b9).
- R11 (the withdrawal mapped back to `no_response`) fails b1.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
