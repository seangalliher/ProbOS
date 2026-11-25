# AD-1358 S2 (#1750): a 1:1 reply that claims a search or lookup is checked against the turn's tool record

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24
**Assembled by:** the orchestrator, 2026-11-25: the heading and pair layout follow what `contract_tools.py` reads; the Status and Base lines follow B13's merge; the Architect's text is otherwise unchanged, except what section 14 records.
**Status:** ready to build; B13 (BF-992, #1324) has merged. **Owning issue:** #1750 (slice S2 of the Architect's ranking, comment 3). Commits and the PR say `Refs #1750.` #1750 stays open for S3.
**Base:** `8704d19468797991298f471ecdf4b7cef3797b88` (origin/main after B13 (BF-992, #1324) merged; the draft was made on `ad28bc34`). B13 shared only `PROGRESS.md`, `DECISIONS.md` and the ledger pair with this item. P3-1 and P3-2 anchor on text that exists on both trees.
**Number:** AD-1358 (a slice; no new number).
**Line endings:** the working copies are CRLF and the blocks below are LF. Every SEARCH starts at a line start and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 45 new cases in 13 functions (one new file); 3 functions in `tests/test_ad1295_tool_success_ledger.py` updated; 0 removed.
**Scope:** new `src/probos/cognitive/dm/lookup_claim.py`; `cognitive/dm/reply_pipeline.py`, `cognitive/agentic_dispatch.py`, `config_models/agentic.py` (docstring and description only); `docs/development/config-reference.md` (regenerated); one new test file; one updated test file; the trackers.

**What S2 alone measures:** on a 1:1 DM turn whose agentic loop called no tool, a reply whose own wording claims a search or record lookup ends with one fixed sentence, and the turn log names the claim.

**What S2 leaves to S3:** claims about shared history ("last time you beat me"), the issue's DM acceptance (the reply contains no such claim and the log names the dropped claim), and the BF-741 check on a retracted claim.

## 1. Problem

On 2026-11-04 (#1750, comment 1), all six of Ezri's replies carried an empty tool trace. Two of them claimed her own lookups:
- "The Ship's Records search turned up nothing either."
- "The record I found shows it as a draw."

The DM write-claim guard checks claimed saves only:
- `assess_write_claim` reads no text (`write_ledger.py:132-153`).
- `step_4n` consults the tool channel only for `publish_finding` (`reply_pipeline.py:64`, `:2395-2397`).

Nothing compares a claimed read with the turn's record.

**The record already reaches the pipeline:**
- `_project_tool_invocations` (`agentic_dispatch.py:2328-2399`) builds names only, per pass.
- Passes are unioned (`cognitive_agent.py:142-161`).
- It rides `IntentResult.metadata["tool_invocations"]` (`cognitive_agent.py:298-312`).
- The route rebuilds it (`routers/agents.py:3838`) into `ctx.tool_invocations`: `None` when the loop did not run, an empty record when it ran and called nothing (`reply_pipeline.py:174-183`).
- An AD-272 cache replay strips it (`cognitive_agent.py:79-99`), so a replay carries no record.
- The record is per turn: a lookup made on a previous turn is not in it. Recall and the passive Oracle injection are not tool calls.

**The gap that would make a check false:** a call whose provider id is null, empty or duplicated is dropped from both lists (`agentic_dispatch.py:2377-2391`). A turn whose every call is dropped yields an empty record today. That would read as "called no tool" (pinned at `test_ad1295_tool_success_ledger.py:823-825`, `:857-859`, `:960-962`).

## 2. Solution

- **New `cognitive/dm/lookup_claim.py`** (runtime-free, beside `write_ledger.py`):
  - `find_lookup_claim(text)` returns the first claim in the reply's own wording (bounded to 80 characters), or `None`. A claim is a past-tense search or record-lookup phrase:
    - outside double quotes, curly quotes, backticks and `>` block quotes;
    - not after `if`, `whether`, `unless`, `have`, `had`, `did`, `not`, `never` or `n't`;
    - not about the agent's memory.
  - `assess_lookup_claim(text, invocations, *, record_incomplete)` returns that claim only when `type(invocations) is ToolInvocations` with empty `attempted` and `succeeded`, and `record_incomplete is False`.
- **In `step_4m`:**
  - After the write verdict, the claim is assessed on `pre_write_disclosure_body`.
  - On a claim, `LOOKUP_DISCLOSURE` is appended after any write sentence, and one WARNING names the claim.
  - `write_disclosure_suffix` holds both sentences.
  - The check sits under the existing `write_claim_guard.enabled`.
- **The `DmReplyContext.lookup_record_incomplete` flag:**
  - Set by step 1 when it adopts a retry, because the retry keeps the first attempt's record.
  - Set by step 4e when it parses `[ACTION:]` envelopes, and by step 4h when it parses a `[MESH ...]` tag. Those reads run outside the record.
- **`_project_tool_invocations`** returns `None` when calls were dropped and none was recorded.
- **Rejected designs (one line each):**
  - A new pipeline step: it changes the 24-step tuple pinned at `test_ad934_deliberate.py:241`, the plan-mode classification (`test_ad1156_plan_mode_reply_tags.py:421-433`), the census (`test_ad1156_plan_mode_side_effects.py:819`) and the order lists (`test_ad811a_a2ui_choice.py:333`, `test_ad1285_write_claim_guard.py:772`).
  - BF-922 `output_grounding.py`: it runs in the agent before the DM tool record exists, and its action is rejection.
  - A list of lookup tool names (`effect_tiers.ROUTINE_TOOL_IDS`): it drifts with every new or renamed reader, and a miss produces a false sentence.
  - Comparing `tool_trace_ref` with the digest of an empty trace: it couples to the serializer, is `None` without a store, and is not carried to the pipeline.
  - A new config flag: it adds pins (`test_ad1270e2i_agentic_models.py:365`, `:565`; the AD-1152 default-config digest) with no measured need.

## 3. Decisions

| # | Decision |
|---|---|
| D1 | **The record decides; the wording selects.** The sentence is "[This turn's tool record is empty: no search or lookup was run through a tool on it.]". It is true of every turn it is appended to, whatever the wording matched. The tool loop is the only search the agent itself runs on the DM path. Passive recall and Oracle injection run without a tool, so the sentence stays true with them. |
| D2 | **Any recorded call abstains**, whatever its name or result. S2 checks only zero-call turns: the live case, and a check that needs no tool taxonomy. |
| D3 | **Append, never remove.** This is AD-1285's #13(c) rule: never block or rewrite the agent's substance. Removing the sentence needs segmentation and could delete true content (the draw was real). A refusal is a capability ceiling. Logging alone leaves the Captain misled. A revision pass is S3. |
| D4 | **Home:** `step_4m` plus a pure module. `DmReplyPipeline` gains no method; its class is frozen as SRP debt in `architecture-baseline.yaml:502-510`. |
| D5 | **Switch:** `write_claim_guard.enabled` (default True). It is a safety control on the same record (the #13(a) reasoning at `agentic.py:833-840`). The field's description is corrected, because "Reads no reply text" stops being true of the switch. |
| D6 | **A record of only unverifiable calls is `None`.** The write verdict is unchanged: `step_4n` returns both for `None` (`:2393-2394`) and for an empty `attempted` (`:2396-2397`). `agent_work_runner.py:384-388` records `tools: []` either way. |
| D7 | **Risk tier STANDARD, crew-facing.** S2 changes what a crew agent's 1:1 reply carries: one appended sentence. No permission, trust, rank or record changes, and no security, governance or audit control is weakened. |
| D8 | **Group replies are untouched.** Group contexts carry `tool_invocations=None` (`thread_fanout.py:848-875`), so the check abstains there. The suffix-equality reconstruction at `thread_fanout.py:889-905` therefore sees the same suffix as before. |

## 4. Milestones, commits, review

One Builder delegation of about 40 tool calls. The Builder applies the pairs and runs no test. The orchestrator commits by plumbing. No subject carries an `AD-` or `BF-` token. No commit or PR text contains the substrings close, fix or resolve; beware "disclose" and "suffix". Every body says `Refs #1750.`

- **M1:** 6.1 (new file), P1-1 to P1-9. Then run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py` and stage `docs/development/config-reference.md`.
  Subject: `DM replies that claim a search on a turn with no tool call carry one appended sentence`
- **M2:** 6.5 (new file), P2-1 to P2-3.
  Subject: `Tests for the lookup-claim check and the record of unverifiable calls`
- **M3:** P3-1 and P3-2, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage the two ledger files if they change.
  Subject: `Trackers for the lookup-claim check on 1:1 replies`

**Shared contracts touched:**
- `step_4m`'s result: `write_disclosure_suffix` may now hold the lookup sentence.
- `DmReplyContext`: one additive defaulted field.
- `_project_tool_invocations`: `None` for an all-unverifiable turn (D6).
- The `write_claim_guard.enabled` description.
- One new WARNING log line.
- No event, journal or wire field.

**Review:** one `gpt-6.1-sol` Diff Reviewer over the whole candidate, using the section 9 properties. Repair rounds review the delta unless a repair changes a shared contract above.

## 5. Builder: may and may not

- **May:** apply the pairs in order, create the two files, run the two generators named in section 4, `git diff --check` and `git diff --stat`.
- **May not:** run pytest, commit, edit an unnamed file, add `skip`/`xfail`, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `src/probos/cognitive/dm/lookup_claim.py` (M1, new file)

```python
"""AD-1358 S2 (#1750): a 1:1 reply that claims a search or lookup, on a turn whose tool record holds no call.

The write-claim guard (AD-1285, ``write_ledger.py``) checks a claimed save against the turn's record of what was
written. This is the read side. The turn's tool record (AD-1295 ``ToolInvocations``: the names of the calls the
agentic loop made) decides; the reply's wording only selects the turns worth a sentence. So the sentence that
``step_4m_write_claim_guard`` appends is true of every turn it is appended to, whatever the wording matched.

``assess_lookup_claim`` abstains (returns None) unless all of these hold: the record is a ``ToolInvocations`` (None
means the loop did not run or its record could not be read, AD-1269); it lists no call; the pipeline saw no
in-reply read and adopted no retry (``record_incomplete`` is exactly False); and ``find_lookup_claim`` finds a claim.

Layer: COGNITIVE and runtime-free: the stdlib and ``probos.dm_reply``. No model call.
"""

from __future__ import annotations

import re

from probos.dm_reply import ToolInvocations

__all__ = ["LOOKUP_DISCLOSURE", "assess_lookup_claim", "find_lookup_claim"]

#: Appended once to the reply. It states a fact of the record, not of the wording, and holds no phrase of
#: ``decomposer._CAPABILITY_GAP_RE`` (a match would misclassify the turn as a capability gap; a test holds it).
LOOKUP_DISCLOSURE = (
    "\n\n[This turn's tool record is empty: no search or lookup was run through a tool on it.]"
)

_MAX_CLAIM_CHARS = 80
_APOS = "['\u2019]"

#: Past-tense claims of a search or record lookup the agent itself made.
_CLAIMS = re.compile(
    r"\bI(?:" + _APOS + r"ve|\s+have)?\s+(?:just\s+|already\s+|also\s+)?"
    r"(?:searched|queried|looked\s+(?:it\s+|that\s+|this\s+|them\s+)?up"
    r"|ran\s+(?:a|another)\s+(?:search|lookup|query)|did\s+(?:a|another)\s+(?:search|lookup)"
    r"|checked\s+(?:the\s+|our\s+|my\s+)?(?:ship" + _APOS + r"s\s+)?"
    r"(?:records?|logs?|archives?|database))\b"
    r"|\b(?:the|my)\s+(?:ship" + _APOS + r"s\s+records\s+|records?\s+)?(?:search|lookup|query)\s+"
    r"(?:turned\s+up|returned|found|came\s+back|shows?|showed)\b"
    r"|\b(?:according\s+to|based\s+on)\s+my\s+(?:search|lookup|query)\b"
    r"|\brecords?\s+I\s+(?:just\s+)?(?:found|pulled|retrieved|looked\s+up)\b",
    re.IGNORECASE,
)
#: Quoted text is not the agent's claim: double and curly quotes, backticks, block-quote lines.
_QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`|^[ \t]*>.*$', re.MULTILINE)
#: A word directly before the match that makes it conditional, a question or a negation.
_NOT_A_CLAIM_BEFORE = re.compile(
    r"(?:\b(?:if|whether|unless|have|had|did|not|never)|n" + _APOS + r"t)\s+$", re.IGNORECASE,
)
#: A search of the agent's own memory is recall, not a tool lookup: left to S3.
_MEMORY_AFTER = re.compile(
    r"\s+(?:through\s+|in\s+)?(?:my|our)\s+(?:own\s+)?(?:memor(?:y|ies)|recall|mind)\b", re.IGNORECASE,
)


def find_lookup_claim(text: object) -> str | None:
    """The first search or lookup claim in ``text``'s own wording, at most 80 characters, or None."""
    if type(text) is not str or not text:
        return None
    masked = _QUOTED.sub(lambda m: " " * len(m.group(0)), text)
    for match in _CLAIMS.finditer(masked):
        if _NOT_A_CLAIM_BEFORE.search(masked[max(0, match.start() - 16):match.start()]):
            continue
        if _MEMORY_AFTER.match(masked, match.end()):
            continue
        return match.group(0)[:_MAX_CLAIM_CHARS]
    return None


def assess_lookup_claim(text: object, invocations: object, *, record_incomplete: object) -> str | None:
    """The claim to disclose for this turn, or None (abstain). The module docstring lists when it abstains."""
    if record_incomplete is not False:
        return None
    if type(invocations) is not ToolInvocations or invocations.attempted or invocations.succeeded:
        return None
    return find_lookup_claim(text)
```

### 6.2 `src/probos/cognitive/dm/reply_pipeline.py` (M1)

**P1-1**
SEARCH:
```python
from probos.admission.seam import shadow_at  # AD-1346 M3c
from probos.cognitive.dm.write_ledger import (  # AD-1285 (#1087)
```
REPLACE:
```python
from probos.admission.seam import shadow_at  # AD-1346 M3c
from probos.cognitive.dm.lookup_claim import (  # AD-1358 S2 (#1750)
    LOOKUP_DISCLOSURE,
    assess_lookup_claim,
)
from probos.cognitive.dm.write_ledger import (  # AD-1285 (#1087)
```

**P1-2**
SEARCH:
```python
    tool_invocations: ToolInvocations | None = None
    owned_steps_view: owned_steps.OwnedStepsView | None = None
```
REPLACE:
```python
    tool_invocations: ToolInvocations | None = None
    # AD-1358 S2 (#1750): True when this reply's reads are not all in ``tool_invocations``: an adopted
    # retry (step 1 keeps the first attempt's record), an ``[ACTION:]`` marker (step 4e) or a
    # ``[MESH ...]`` read (step 4h). The lookup-claim check in step 4m abstains when it is set.
    lookup_record_incomplete: bool = False
    owned_steps_view: owned_steps.OwnedStepsView | None = None
```

**P1-3**
SEARCH:
```python
                        self.ctx.reply = self.ctx.reply.replaced_by(
                            DmReply.from_intent_result(retry_resp).with_body(
                                retry_result.cleaned_text
                            )
                        )
```
REPLACE:
```python
                        self.ctx.reply = self.ctx.reply.replaced_by(
                            DmReply.from_intent_result(retry_resp).with_body(
                                retry_result.cleaned_text
                            )
                        )
                        # AD-1358 S2 (#1750): ``ctx.tool_invocations`` is still the first
                        # attempt's record, so the lookup-claim check abstains for this reply.
                        self.ctx.lookup_record_incomplete = True
```

**P1-4**
SEARCH:
```python
        envelopes = parse_action_envelopes(self.ctx.response_text)
        if not envelopes:
            return
```
REPLACE:
```python
        envelopes = parse_action_envelopes(self.ctx.response_text)
        if not envelopes:
            return
        # AD-1358 S2 (#1750): a browser action the reply asked for runs (or is refused) outside the
        # tool record, so the lookup-claim check in step 4m abstains for this reply.
        self.ctx.lookup_record_incomplete = True
```

**P1-5**
SEARCH:
```python
        intent_name, params = parsed

        pool_name = _MESH_READ_INTENT_POOLS.get(intent_name)
```
REPLACE:
```python
        intent_name, params = parsed
        # AD-1358 S2 (#1750): a read the reply asked for runs here, outside the tool record, so the
        # lookup-claim check in step 4m abstains for this reply, whether or not the read runs.
        self.ctx.lookup_record_incomplete = True

        pool_name = _MESH_READ_INTENT_POOLS.get(intent_name)
```

**P1-6**
SEARCH:
```python
        (``MARKER_WROTE_PARTIALLY``, BF-866 #1338 item 4). The reply is only
        the surface the disclosure lands on; no text is read.
        Never blocks and never rewrites the agent's substance (#13(c): a
        refusal that ends the work is a capability ceiling in a governance
        costume).

        Abstains whenever no channel ran, so a ship with no write channel
        wired is byte-identical.
```
REPLACE:
```python
        (``MARKER_WROTE_PARTIALLY``, BF-866 #1338 item 4). The write verdict
        reads no text.
        AD-1358 S2 (#1750): under the same switch, one more sentence
        (``LOOKUP_DISCLOSURE``) when the reply's wording claims a search or
        lookup and the turn's tool record holds no call; the record decides
        and the wording only selects (``lookup_claim.py``).
        Never blocks and never rewrites the agent's substance (#13(c): a
        refusal that ends the work is a capability ceiling in a governance
        costume).

        The write verdict abstains whenever no channel ran; the lookup check
        abstains unless ``ctx.tool_invocations`` is a record with no call.
```

**P1-7**
SEARCH:
```python
            verdict = assess_write_claim(self.ctx.write_ledger)
            if verdict is ClaimVerdict.ABSTAIN:
                return

            logger.warning(
                "AD-1285: write-claim guard verdict=%s agent=%s thread=%s "
                "ran_without_writing=%s wrote_partially=%s wrote=%s",
                verdict.value,
                self.ctx.agent_id,
                self.ctx.chat_thread_id,
                sorted(self.ctx.write_ledger.wrote_nothing),
                sorted(self.ctx.write_ledger.wrote_partially),
                sorted(self.ctx.write_ledger.wrote),
            )
            suffix = disclosure_for(verdict)
            self.ctx.response_text = self.ctx.response_text + suffix
            self.ctx.write_disclosure_suffix = suffix
```
REPLACE:
```python
            verdict = assess_write_claim(self.ctx.write_ledger)
            suffix = ""
            if verdict is not ClaimVerdict.ABSTAIN:
                logger.warning(
                    "AD-1285: write-claim guard verdict=%s agent=%s thread=%s "
                    "ran_without_writing=%s wrote_partially=%s wrote=%s",
                    verdict.value,
                    self.ctx.agent_id,
                    self.ctx.chat_thread_id,
                    sorted(self.ctx.write_ledger.wrote_nothing),
                    sorted(self.ctx.write_ledger.wrote_partially),
                    sorted(self.ctx.write_ledger.wrote),
                )
                suffix = disclosure_for(verdict)
            # AD-1358 S2 (#1750): the read side, after the write sentence. The tool record
            # decides; the wording of the body before any sentence only selects the turn.
            claim = assess_lookup_claim(
                self.ctx.pre_write_disclosure_body,
                self.ctx.tool_invocations,
                record_incomplete=self.ctx.lookup_record_incomplete,
            )
            if claim is not None:
                logger.warning(
                    "AD-1358: lookup-claim check agent=%s thread=%s claim=%r: the reply "
                    "claims a search or lookup and the turn's tool record holds no call",
                    self.ctx.agent_id,
                    self.ctx.chat_thread_id,
                    claim,
                )
                suffix += LOOKUP_DISCLOSURE
            if not suffix:
                return
            self.ctx.response_text = self.ctx.response_text + suffix
            self.ctx.write_disclosure_suffix = suffix
```

### 6.3 `src/probos/cognitive/agentic_dispatch.py` (M1)

**P1-8**
SEARCH:
```python
                len(dropped), sorted(set(dropped)),
            )
        return ToolInvocations.from_names(attempted, succeeded)
```
REPLACE:
```python
                len(dropped), sorted(set(dropped)),
            )
        if dropped and not attempted:
            # AD-1358 S2 (#1750): every call was unverifiable, so an empty record would say "this turn
            # called no tool", which it did. None says the record cannot be read (AD-1269). The write
            # verdict is the same either way: ``step_4n`` consults no channel for None or for an
            # empty ``attempted``.
            return None
        return ToolInvocations.from_names(attempted, succeeded)
```

### 6.4 `src/probos/config_models/agentic.py` (M1)

**P1-9**
SEARCH:
```python
    mode #1087 names. It is safe on because ``assess_write_claim`` abstains on
    an unpopulated ledger, so a ship with no durable-write channel wired is
    byte-identical. The flag exists so the behaviour can be turned off without
    a revert.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "AD-1285 (#1087): check a 1:1 reply against the turn's write "
            "ledger and append one honest sentence when a durable-write "
            "channel ran and wrote nothing. Reads no reply text. Default ON "
            "because this is a safety control rather than a capability, and a "
            "default-OFF control defends nothing (#13(a)) -- which is the "
            "AD-1157 failure mode #1087 names. Safe on: the verdict abstains "
            "unless a channel actually ran, so a turn with no write marker is "
            "byte-identical."
        ),
```
REPLACE:
```python
    mode #1087 names. It is safe on because ``assess_write_claim`` abstains on
    an unpopulated ledger, so a ship with no durable-write channel wired is
    byte-identical for writes. AD-1358 S2 (#1750) puts its lookup-claim check
    under the same flag; it abstains unless the turn's tool record is present
    and holds no call. The flag exists so the behaviour can be turned off
    without a revert.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "AD-1285 (#1087): check a 1:1 reply against the turn's write "
            "ledger and append one honest sentence when a durable-write "
            "channel ran and wrote nothing; that verdict reads no reply text. "
            "AD-1358 S2 (#1750): the same switch appends one sentence when the "
            "reply's wording claims a search or lookup and the turn's tool "
            "record holds no call. Default ON "
            "because this is a safety control rather than a capability, and a "
            "default-OFF control defends nothing (#13(a)) -- which is the "
            "AD-1157 failure mode #1087 names. Safe on: each check abstains "
            "unless its record shows the case (a channel that ran; a tool "
            "record with no call)."
        ),
```

### 6.5 `tests/test_ad1358_s2_lookup_claim.py` (M2, new file)

```python
"""AD-1358 S2 (#1750): a reply that claims a search or lookup, on a turn whose tool record holds no call.

Contract: prompts/ad-1358-s2-lookup-claim-trace.md. Real objects: the real projection, observation fold, act()
override and metadata builder (``_turn_metadata_for``), a real IntentResult, the route's reconstruction and the
real pipeline. Nothing mocks the check's input.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.dm.lookup_claim import LOOKUP_DISCLOSURE, assess_lookup_claim, find_lookup_claim
from probos.cognitive.dm.reply_pipeline import DmReplyPipeline
from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import WriteClaimGuardConfig
from probos.dm_reply import ToolInvocations
from probos.types import IntentResult
from tests.test_ad1295_tool_success_ledger import (
    _CapturingEpisodicMemory,
    _FakeProactiveLoop,
    _agentic_result,
    _agentic_result_with_ids,
    _make_ctx,
    _runtime,
    _turn_metadata_for,
)

_LOGGER = "probos.cognitive.dm.reply_pipeline"
_CLAIM = "I searched the records and found two games."
#: The two sentences of the live case (#1750, 2026-11-04), each sent on a turn with an empty tool trace.
_LIVE = [
    pytest.param("Good game, Captain. The record I found shows it as a draw.", "record I found", id="record-i-found"),
    pytest.param("The Ship's Records search turned up nothing either.", "search turned up", id="records-search"),
]


def _ctx_for_turn(agentic_result, reply: str, *, runtime=None):
    """The route's own reconstruction (``routers/agents.py:3838``) over the real producer chain."""
    result = IntentResult(
        intent_id="i-1", agent_id="a1", success=True, result=reply,
        metadata=_turn_metadata_for(agentic_result),
    )
    ctx = _make_ctx(
        runtime=runtime if runtime is not None else _runtime(episodic=_CapturingEpisodicMemory()),
        response_text=reply,
        tool_invocations=ToolInvocations.from_intent_result(result),
    )
    ctx.req_message = ctx.message_text = "Hello Ezri"
    return ctx


@pytest.mark.parametrize(("reply", "phrase"), _LIVE)
def test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed(reply, phrase, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    episodic = _CapturingEpisodicMemory()
    ctx = _ctx_for_turn(_agentic_result([]), reply, runtime=_runtime(episodic=episodic))
    assert ctx.tool_invocations == ToolInvocations(), "premise: the route rebuilt an empty record, not None"

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.response_text == reply + LOOKUP_DISCLOSURE
    assert DmReplyPipeline(ctx).build_response()["response"] == reply + LOOKUP_DISCLOSURE
    assert episodic.stored[0].outcomes[0]["response"] == reply + LOOKUP_DISCLOSURE
    assert any("AD-1358" in r.getMessage() and phrase in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("text", "expected"), [
    pytest.param("The Ship's Records search turned up nothing either.", "search turned up", id="records-search"),
    pytest.param("The record I found shows it as a draw.", "record I found", id="record-i-found"),
    pytest.param(_CLAIM, "I searched", id="i-searched"),
    pytest.param("My search shows two wins.", "My search shows", id="my-search"),
    pytest.param("I checked the logs before answering.", "checked the logs", id="checked-logs"),
    pytest.param("I've looked it up: two games.", "looked it up", id="looked-it-up"),
    pytest.param("I ran a search for tictactoe.", "ran a search", id="ran-a-search"),
    pytest.param("According to my search, you won twice.", "my search", id="according-to"),
    pytest.param("The Ship\u2019s Records search turned up nothing.", "search turned up", id="curly-apostrophe"),
    pytest.param("I\u2019ve searched the archive.", "searched", id="curly-ive"),
])
def test_claim_wording_is_found(text, expected) -> None:
    found = find_lookup_claim(text)
    assert found is not None and expected.lower() in found.lower()


@pytest.mark.parametrize("text", [
    pytest.param('You wrote "I searched the records" earlier.', id="quoted"),
    pytest.param("You wrote \u201cI searched the records\u201d earlier.", id="curly-quoted"),
    pytest.param("Run `I searched` as a test phrase.", id="backticks"),
    pytest.param("> I searched the records\nThat was your line.", id="block-quote"),
    pytest.param("I haven't searched the records yet.", id="havent"),
    pytest.param("I have not searched the records.", id="have-not"),
    pytest.param("I never searched the records.", id="never"),
    pytest.param("I didn't search the records.", id="didnt"),
    pytest.param("If I searched the records, I would know.", id="if"),
    pytest.param("Have I searched the records?", id="question"),
    pytest.param("I'll search the records now.", id="future"),
    pytest.param("Let me look it up.", id="offer"),
    pytest.param("I searched my memory and found nothing.", id="memory"),
    pytest.param("I checked in with Bones.", id="checked-in"),
    pytest.param("Your search turned up two games.", id="your-search"),
    pytest.param("", id="empty"),
])
def test_wording_that_is_not_a_claim_is_not_found(text) -> None:
    assert find_lookup_claim(text) is None


@pytest.mark.parametrize(("invocations", "incomplete", "fires"), [
    pytest.param(None, False, False, id="no-record"),
    pytest.param(SimpleNamespace(attempted=(), succeeded=()), False, False, id="look-alike"),
    pytest.param(ToolInvocations.from_names(["oracle_query"], ["oracle_query"]), False, False, id="lookup-ran"),
    pytest.param(ToolInvocations.from_names(["oracle_query"], []), False, False, id="lookup-failed"),
    pytest.param(ToolInvocations.from_names(["publish_finding"], ["publish_finding"]), False, False, id="other-tool"),
    pytest.param(ToolInvocations(), True, False, id="incomplete"),
    pytest.param(ToolInvocations(), 1, False, id="incomplete-not-a-bool"),
    pytest.param(ToolInvocations(), False, True, id="empty-record"),
])
def test_the_record_decides(invocations, incomplete, fires) -> None:
    found = assess_lookup_claim(_CLAIM, invocations, record_incomplete=incomplete)
    assert (found is not None) is fires


def test_a_lookup_that_ran_leaves_the_reply_byte_identical() -> None:
    reply = "I searched the records: two games, you won both."
    ctx = _ctx_for_turn(_agentic_result([("oracle_query", True)]), reply)
    assert ctx.tool_invocations is not None and ctx.tool_invocations.attempted == ("oracle_query",)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed() -> None:
    """An empty record must not stand for a turn that did call a tool (``_project_tool_invocations``)."""
    reply = "I searched the records: two games."
    ctx = _ctx_for_turn(_agentic_result_with_ids([("oracle_query", True, None)]), reply)
    assert ctx.tool_invocations is None
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_the_write_claim_switch_turns_the_lookup_check_off() -> None:
    reply = "The record I found shows it as a draw."
    runtime = _runtime(episodic=_CapturingEpisodicMemory(), guard_enabled=False)
    ctx = _ctx_for_turn(_agentic_result([]), reply, runtime=runtime)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_a_write_disclosure_and_a_lookup_disclosure_compose() -> None:
    runtime = _runtime(proactive=_FakeProactiveLoop(actions=[]), episodic=_CapturingEpisodicMemory())
    ctx = _ctx_for_turn(
        _agentic_result([]),
        "I searched the records first. [NOTEBOOK finding]Ward room escalation.[/NOTEBOOK]",
        runtime=runtime,
    )
    asyncio.run(DmReplyPipeline(ctx).run())
    both = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING) + LOOKUP_DISCLOSURE
    assert find_lookup_claim(ctx.pre_write_disclosure_body) is not None
    assert ctx.write_disclosure_suffix == both
    assert ctx.response_text == ctx.pre_write_disclosure_body + both


def test_a_mesh_read_in_the_reply_makes_the_check_abstain() -> None:
    ctx = _ctx_for_turn(_agentic_result([]), "I searched the files. [MESH remove_files path=/tmp]")
    ctx.sanity_gate = DmSanityGate()
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4h_mesh_read_parse())
    asyncio.run(pipeline.step_4m_write_claim_guard())
    assert ctx.lookup_record_incomplete is True
    assert find_lookup_claim(ctx.response_text) is not None, "premise: the claim is still in the reply"
    assert LOOKUP_DISCLOSURE not in ctx.response_text


def test_an_action_marker_in_the_reply_makes_the_check_abstain() -> None:
    runtime = SimpleNamespace(config=SimpleNamespace(
        write_claim_guard=WriteClaimGuardConfig(),
        browser_tool=SimpleNamespace(action_dispatch_enabled=True),
    ))
    ctx = _ctx_for_turn(
        _agentic_result([]), 'I looked it up. [ACTION: {"verb": "state", "intent": "read the page"}]',
        runtime=runtime,
    )
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4e_action_dispatch())
    asyncio.run(pipeline.step_4m_write_claim_guard())
    assert ctx.lookup_record_incomplete is True
    assert find_lookup_claim(ctx.response_text) is not None, "premise: the claim is still in the reply"
    assert LOOKUP_DISCLOSURE not in ctx.response_text


class _RetryBus:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sent: list = []

    async def send(self, intent):
        self.sent.append(intent)
        return IntentResult(intent_id="i-2", agent_id="a1", success=True, result=self.text)


def test_an_adopted_retry_makes_the_check_abstain() -> None:
    bus = _RetryBus("The record I found shows it as a draw.")
    runtime = SimpleNamespace(config=SimpleNamespace(write_claim_guard=WriteClaimGuardConfig()), intent_bus=bus)
    ctx = _ctx_for_turn(_agentic_result([]), "Ok", runtime=runtime)
    ctx.sanity_gate = DmSanityGate()
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_1_sanity_gate_retry())
    assert bus.sent and "record I found" in ctx.response_text, "premise: the length floor adopted a retry"
    asyncio.run(pipeline.step_4m_write_claim_guard())
    assert ctx.lookup_record_incomplete is True
    assert LOOKUP_DISCLOSURE not in ctx.response_text


def test_the_captains_words_are_never_read() -> None:
    reply = "Hello, Captain. Ready when you are."
    ctx = _ctx_for_turn(_agentic_result([]), reply)
    ctx.req_message = ctx.message_text = _CLAIM
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_the_disclosure_is_ascii_and_not_a_capability_gap() -> None:
    assert LOOKUP_DISCLOSURE.isascii()
    assert not is_capability_gap(LOOKUP_DISCLOSURE)
    assert find_lookup_claim(LOOKUP_DISCLOSURE) is None
```

### 6.6 `tests/test_ad1295_tool_success_ledger.py` (M2)

**P2-1**
SEARCH:
```python
    inv = _project_tool_invocations(_agentic_result_with_ids([(FINDING, True, bad_id)]))

    assert inv is not None
    assert inv.attempted == ()
    assert inv.succeeded == ()
```
REPLACE:
```python
    inv = _project_tool_invocations(_agentic_result_with_ids([(FINDING, True, bad_id)]))

    # AD-1358 S2 (#1750): was an empty record. With every call unverifiable the record is None, so
    # an empty one always means "called no tool"; the write guard abstains for both (step_4n).
    assert inv is None
```

**P2-2**
SEARCH:
```python
            [(FINDING, True, "same"), ("read_file", False, "same")]
        )
    )

    assert inv is not None
    assert inv.attempted == ()
    assert inv.succeeded == ()
```
REPLACE:
```python
            [(FINDING, True, "same"), ("read_file", False, "same")]
        )
    )

    # AD-1358 S2 (#1750): was an empty record; every call is unverifiable, so the record is None.
    assert inv is None
```

**P2-3**
SEARCH:
```python
    before = ctx.response_text
    assert ctx.tool_invocations is not None
    assert ctx.tool_invocations.attempted == ()
    assert ctx.tool_invocations.succeeded == ()
```
REPLACE:
```python
    before = ctx.response_text
    # AD-1358 S2 (#1750): was an empty record; every call is unverifiable, so there is no record.
    # The assertions below (no write sentence, an untouched ledger) are unchanged.
    assert ctx.tool_invocations is None
```

### 6.7 `PROGRESS.md` (M3)

**P3-1**
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1358 S2 (2026-11-25), #1750 -- a 1:1 reply that says it searched or looked something up, on a turn whose tool record holds no call, carries one appended sentence.** New `cognitive/dm/lookup_claim.py`: `find_lookup_claim` reads the reply's own wording (outside double quotes, backticks and block quotes) for a past-tense search or record-lookup claim that is not negated, conditional, a question or about the agent's memory; `assess_lookup_claim` returns it only when the turn's `ToolInvocations` is present and lists no call and `DmReplyContext.lookup_record_incomplete` is False (set by steps 1, 4e and 4h for an adopted retry, an `[ACTION:]` marker and a `[MESH]` read). `step_4m_write_claim_guard` appends `LOOKUP_DISCLOSURE` after any write sentence, under `write_claim_guard.enabled`, and logs the claim at WARNING. `_project_tool_invocations` returns None when every call's id is unverifiable. Measured by `tests/test_ad1358_s2_lookup_claim.py` (13 functions, 45 cases): the two live sentences of 2026-11-04, on a turn with an empty record, through the real producer chain and `DmReplyPipeline.run()`, end with the sentence in the reply, the response and the episode, and the log names the claim; a turn whose lookup ran, a turn whose only call had an unverifiable id, the switch off, a `[MESH]` read, an `[ACTION:]` marker, an adopted retry and the Captain's own words leave the reply unchanged; 16 wordings are not claims; the write and lookup sentences compose. Three pins in `tests/test_ad1295_tool_success_ledger.py` now expect no record for an all-unverifiable turn. Mutation census: 19 of 19 killed, each by a test the contract names (rows LC-1 to LC-19), run once on the candidate overlay of `8704d194`. Not measured: a live DM turn. Claims about shared history and the issue's DM acceptance are S3. Contract `prompts/ad-1358-s2-lookup-claim-trace.md`.
```

### 6.8 `DECISIONS.md` (M3)

**P3-2**
SEARCH:
```markdown
### AD-1358 S1 -- A crew member in a game is told the recorded games against that opponent (2026-11-06, #1750)
```
REPLACE:
```markdown
### AD-1358 S2 -- A reply that claims a search or lookup is checked against the turn's tool record (2026-11-25, #1750)

- *Scope.* `cognitive/dm/lookup_claim.py` (new), `cognitive/dm/reply_pipeline.py` (`step_4m`, the `lookup_record_incomplete` field, steps 1, 4e and 4h), `cognitive/agentic_dispatch.py` (`_project_tool_invocations`), the `write_claim_guard.enabled` description; tests. Contract `prompts/ad-1358-s2-lookup-claim-trace.md`.
- *LC1 (the record decides).* The sentence states a fact of the turn's AD-1295 tool record ("no search or lookup was run through a tool on it"); the reply's wording only selects the turns. Any recorded call abstains, whatever its name or result. Rejected: a list of lookup tool names (drifts with every reader); the trace digest (serializer-bound, absent without a store).
- *LC2 (action).* Append one sentence and log the claim, as AD-1285 does for saves (#13(c)). Rejected: removing the sentence (it can carry true content), refusing the reply, logging only, a revision pass (S3).
- *LC3 (home).* `step_4m` with a pure module beside `write_ledger.py`; no new step. Rejected: a new step (the step tuple, plan-mode and census pins); BF-922 `output_grounding.py` (runs before the DM tool record exists).
- *LC4 (switch).* `write_claim_guard.enabled`, default on; no new field.
- *LC5 (unverifiable ids).* A record whose every call was unverifiable is None, not empty; the write verdict is unchanged.
- *Not changed.* `write_ledger.py`, `ToolInvocations` and its wire shape, the step tuples, the group fan-out, config fields.
- *Residual.* Limits L1 to L9 and finding F1 of the contract.
- *Reversal.* Revert the S2 commits, or set `write_claim_guard.enabled: false` (which also turns off the write sentence).

### AD-1358 S1 -- A crew member in a game is told the recorded games against that opponent (2026-11-06, #1750)
```

## 7. Consumers

| Contract | Checked | Result |
|---|---|---|
| `write_disclosure_suffix`, `pre_write_disclosure_body` | `reply_pipeline.py:172-173`, `:2437-2438`, `:2464`; `thread_fanout.py:885-911` (group only, `tool_invocations=None`) | Group unchanged (D8); 1:1 suffix may hold the lookup sentence |
| The 1:1 reply | `routers/agents.py:3814-3857` (`build_response`, thread append); step 5 stores `response_text[:500]` (`reply_pipeline.py:2553`) | Body text gains the sentence; no new field |
| `ToolInvocations` `None` for an all-unverifiable turn | `reply_pipeline.py:2392-2397`; `agent_work_runner.py:384-388`; `cognitive_agent.py:153-161` (a `None` pass leaves the prior record), `:306-311` (key omitted) | Same write verdict and work-item result (D6) |
| `DmReplyPipeline` construction | `routers/agents.py:3814`, `thread_fanout.py:876`, `reply_pipeline.py:2751` (plan-mode text, no record) | Only the first can reach the check |
| AD-1357 (#1749) | The journal row hashes the agent's output before the pipeline (`cognitive_agent.py:4543-4559`); the manifest records inputs | Unchanged |
| Plan mode | `step_4m` is allowed (`reply_pipeline.py:410`); step 4e is withheld, and its pass sets no flag, so the sentence stays true there | Unchanged sets |
| HXI `ui/src` | No match for `AD-1285`, `write_ledger`, `ClaimVerdict` or `step_4m` | Text only |
| Config | `test_ad1270e2i_agentic_models.py:565` (field names); `config-reference.md:1895` (regenerated) | No field added |

**Not checked:** the Counselor's reading of DM episodes; how the HXI renders a bracketed sentence (the same as AD-1285's).

## 8. Gates (the orchestrator runs all of them)

**First-hand checks on the oracle tree, before the Builder starts:**
1. Every SEARCH matches exactly once: P1-1 to P1-9, P2-1 to P2-3, P3-1, P3-2. Expected: 14 of 14.
2. `rg -n "lookup_claim|LOOKUP_DISCLOSURE|lookup_record_incomplete" src tests`. Expected: no hits.
3. `rg -n "DmReplyPipeline\(" src`. Expected: three lines (`routers/agents.py:3814`, `routers/thread_fanout.py:876`, `cognitive/dm/reply_pipeline.py:2751`).
4. Probe: `_project_tool_invocations(AgenticResult(final_text="", tool_calls=[ToolCallRequest(name="oracle_query", arguments={}, id=None)], tool_results=[]))`. Expected: `ToolInvocations(attempted=(), succeeded=())`, the value P1-8 removes.
5. Copy 6.5 onto the oracle without the source pairs and collect it at `-n 0`. Expected: `ModuleNotFoundError` for `probos.cognitive.dm.lookup_claim`.
6. On the candidate: `gen_config_reference.py --check`. Expected: exit 0.

**Focused gate on the frozen candidate:**
```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1358_s2_lookup_claim.py tests/test_ad1295_tool_success_ledger.py tests/test_ad1285_write_claim_guard.py tests/test_ad1293_turn_record_reaches_episode.py tests/test_bf866_artifact_channel_seams.py tests/test_ad933_group_chat_escalation.py tests/test_ad1156_plan_mode_reply_tags.py tests/test_ad1156_plan_mode_side_effects.py tests/test_ad1156_plan_mode_containment.py tests/test_ad1156_plan_mode_learning.py tests/test_ad934_deliberate.py tests/test_ad1192_owned_steps_dm.py tests/test_ad726_dm_reply_pipeline.py tests/test_ad869_mesh_read_inline.py tests/test_ad745_pipeline_dispatch.py tests/test_ad724_dm_sanity_gate.py tests/test_ad724_dm_hardening.py tests/test_ad1162_captain_session_binding.py tests/test_ad856_agentic_dispatch.py tests/test_ad1270e2i_agentic_models.py tests/test_config_reference_current.py tests/test_ad1343_stop_seam_inventory.py -q -n 0
```
Then run the broad gate once: `scripts/run_test_gate.py --label ad-1358-s2 --receipt logs/gates/ad-1358-s2.receipt.json`.

**Mutation census.** Run it once on the candidate overlay and mark it the campaign of record, with each pinned file's sha256. "File" below means `tests/test_ad1358_s2_lookup_claim.py`.

| Row | Mutant | Killer (File unless named) |
|---|---|---|
| LC-1 | `assess`: drop `or invocations.attempted or invocations.succeeded` | `test_the_record_decides[lookup-ran, lookup-failed, other-tool]`, `test_a_lookup_that_ran_leaves_the_reply_byte_identical` |
| LC-2 | `type(invocations) is not ToolInvocations` becomes `invocations is None` | `test_the_record_decides[look-alike]` |
| LC-3 | `record_incomplete is not False` becomes `is True` | `test_the_record_decides[incomplete-not-a-bool]` |
| LC-4 | Drop the `record_incomplete` check | `[incomplete]`, and the mesh, action and retry tests |
| LC-5 | `find`: no quote masking | `test_wording_that_is_not_a_claim_is_not_found[quoted, curly-quoted, backticks, block-quote]` |
| LC-6 | `find`: drop the before-window | `...[if, question]` |
| LC-7 | `find`: drop the memory check | `...[memory]` |
| LC-8 | `_CLAIMS`: drop the `records? I found` branch | `test_claim_wording_is_found[record-i-found]`, the crossing `[record-i-found]` |
| LC-9 | `step_4m`: delete the lookup block | The crossing (both cases), the compose test |
| LC-10 | `step_4m`: lookup block nested under the write verdict | The crossing |
| LC-11 | `step_4m`: `suffix = LOOKUP_DISCLOSURE` instead of `+=` | The compose test |
| LC-12 | `step_4m`: assess `self.ctx.req_message` | The crossing, `test_the_captains_words_are_never_read` |
| LC-13 | `step_4m`: lookup block before the `enabled` check | `test_the_write_claim_switch_turns_the_lookup_check_off` |
| LC-14 | Step 1 flag line deleted | `test_an_adopted_retry_makes_the_check_abstain` |
| LC-15 | Step 4e flag line deleted | `test_an_action_marker_in_the_reply_makes_the_check_abstain` |
| LC-16 | Step 4h flag line deleted | `test_a_mesh_read_in_the_reply_makes_the_check_abstain` |
| LC-17 | P1-8 deleted | `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed`; `test_ad1295::test_unverifiable_call_is_omitted_from_attempted`, `::test_duplicate_call_ids_are_uncorrelatable` |
| LC-18 | P1-8 condition becomes `if dropped:` | `test_ad1295::test_uncorrelatable_call_does_not_hide_its_well_formed_sibling` |
| LC-19 | Sentence reworded to contain "no tool" | `test_the_disclosure_is_ascii_and_not_a_capability_gap` |

## 9. Diff Reviewer: properties to verify

1. The lookup sentence is appended only when all of these hold: `type(ctx.tool_invocations) is ToolInvocations` with empty `attempted` and `succeeded`; `lookup_record_incomplete is False`; `write_claim_guard.enabled` is on; and a claim is found. Every other path leaves the reply byte-identical.
2. The sentence is true of every turn it is appended to, whatever wording matched. It names the record, not the agent's words.
3. The write verdict, its log line and its sentence are unchanged for every ledger. When both apply, the write sentence comes first and `write_disclosure_suffix` holds both. `pre_write_disclosure_body` still holds the body before both.
4. `_project_tool_invocations` returns `None` only when calls were dropped and none was recorded. For every other input its output is as before. The write ledger's consulted set is identical for every input.
5. The checker reads only the reply body passed by `step_4m`, never `req_message` or `message_text`.
6. `_full_steps`, `_escalation_steps` and the three plan-mode sets are unchanged. `DmReplyPipeline` gains no method.
7. The flag is set in step 1 only on an adopted retry (the valid-result branch), in 4e only when envelopes were parsed, and in 4h only when a tag was parsed.
8. The new module imports only the stdlib and `probos.dm_reply`. All new text is ASCII. The sentence holds no `_CAPABILITY_GAP_RE` phrase.
9. `config-reference.md` matches the source (`--check`). No config field is added.
10. Each updated pin in `test_ad1295` carries its reason inline, and its test still asserts that the write guard abstains.
11. Each tracker head holds no ledger status word in its first 120 characters. Every behaviour sentence maps to a named test.

## 10. Verified Against Codebase (2026-11-24, tree `ad28bc34`)

```
reply_pipeline.py:31-41       write_ledger import block; dm_reply import (DmReply, ToolInvocations)
reply_pipeline.py:64          _DURABLE_WRITE_TOOLS = frozenset({"publish_finding"})
reply_pipeline.py:172-183     pre_write_disclosure_body / write_disclosure_suffix / tool_invocations: ToolInvocations | None = None
reply_pipeline.py:402-416     _PLAN_MODE_ALLOWED_STEPS (step_4m allowed)
reply_pipeline.py:489-514     _full_steps (24); :550-562 _escalation_steps (includes step_4m)
reply_pipeline.py:703-707     self.ctx.reply = self.ctx.reply.replaced_by(  (only occurrence)
reply_pipeline.py:1057-1059   envelopes = parse_action_envelopes(self.ctx.response_text) / if not envelopes: return
reply_pipeline.py:1412-1417   parsed = gate.extract_mesh_read(...) / intent_name, params = parsed / pool_name = ...
reply_pipeline.py:2392-2397   step_4n: not ToolInvocations -> return; attempted & durable empty -> return
reply_pipeline.py:2418-2470   step_4m: suffix reset, enabled check, assess_write_claim, disclosure_for
reply_pipeline.py:2553        "response": self.ctx.response_text[:500]
write_ledger.py:132-176       assess_write_claim (no text); _DISCLOSURES; disclosure_for
dm_reply.py:146               TOOL_INVOCATIONS_METADATA_KEY = "tool_invocations"
dm_reply.py:560-702           ToolInvocations(attempted, succeeded), from_names, to_wire, from_wire, from_intent_result
agentic_dispatch.py:2269-2276 _is_correlatable; :2328-2399 _project_tool_invocations (dropped from both lists; :2392 return)
cognitive_agent.py:79-99      _PER_RUN_PROVENANCE_KEYS includes "_dm_tool_invocations"; _cacheable_decision
cognitive_agent.py:142-161    _accumulate_pass_invocations (None pass leaves prior); :5259 call site
cognitive_agent.py:298-312    metadata[TOOL_INVOCATIONS_METADATA_KEY] = invocations.to_wire()
routers/agents.py:3838        tool_invocations=ToolInvocations.from_intent_result(result)
thread_fanout.py:848-911      group DmReplyContext (no tool_invocations); run_escalation_only; suffix equality
config_models/agentic.py:830-854  WriteClaimGuardConfig.enabled, "Reads no reply text" at :847
decomposer.py:52-70           _CAPABILITY_GAP_RE ("no ... tool" matches), is_capability_gap
dm_sanity_gate.py:74,161,170-173,334-362  _MESH_READ_RE; length_floor 5; retry_warnings; extract/strip_mesh_read
action_parser.py:27,44-87     _ACTION_RE; parse_action_envelopes needs "verb"
agent_stop.py:566-577; admission/seam.py:40-50  active_stop / shadow_at return None for a None service
tests/test_ad1295_tool_success_ledger.py:92,107,137,147,172,188,785  helpers imported by 6.5
tests/test_ad1295_tool_success_ledger.py:823-825,857-859,960-962  the three pins P2-1..P2-3
types.py:78-104               IntentResult(result=None, metadata default_factory=dict)
```

### Absence Verified (2026-11-24)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No lookup-claim check exists | `rg -n "lookup_claim\|LOOKUP_DISCLOSURE\|lookup_record_incomplete\|claimed lookup" src` | nothing | yes |
| Only three pipeline constructions | `rg -n "DmReplyPipeline\(\|DmReplyContext\(" src` | `agents.py:3814`, `thread_fanout.py:848/876`, `reply_pipeline.py:2734/2751` | yes |
| The suffix and pre-body have no other reader | `rg -n "write_disclosure_suffix\|pre_write_disclosure_body" src` | `reply_pipeline.py`, `thread_fanout.py` only | yes |
| No test runs the pipeline on a lookup phrase | the `_CLAIMS` pattern over `tests/` | `test_ad1242_crew_verifier_trace.py` (crew verifier, not the DM pipeline), prose lines in five other files | yes |
| No test enumerates `DmReplyContext` fields | `rg -n "fields\(DmReplyContext\|DmReplyContext.__dataclass_fields__" tests` | nothing | yes |
| No test pins the description text | `rg -n "Reads no reply text"` (repo) | `src` (2), `config-reference.md` (2), `PROGRESS.md:771`, an old prompt | yes |
| HXI has no guard type | `rg -l "AD-1285\|write_ledger\|ClaimVerdict\|step_4m" ui/src` | nothing | yes |
| All-unverifiable pins | `rg -n "_project_tool_invocations\|uncorrelatable" tests` | `test_ad1295` only (plus prose at `test_ad1240:3961`) | yes |

## 11. Prior art and blind spots

**Internal prior art** (external review skipped: ProbOS-specific plumbing; internal sources were enough for this slice):
- **AD-1285, AD-1295 (#1087):** the write side of the same control. Adopted: its record, its append-only action and its switch.
- **AD-1269:** `None` versus empty. Adopted, and extended to unverifiable ids (D6).
- **AD-1242:** the crew verifier gives the model "the agent's tool trace, not its narration" (`crew_verifier.py:1405`). Same principle, deterministic here.
- **BF-922 `output_grounding.py`:** rejected as the home (section 2).
- **AD-981b and AD-979b:** they cover answers to questions; claims the agent volunteers go to S3.

**Recorded limits (blind spots):**
- **L1:** a lookup made on an earlier turn and cited now gets the sentence. The sentence remains true of this turn.
- **L2:** a turn with any tool call (for example only `publish_finding`, or a lookup that failed) is not checked.
- **L3:** passive recall and Oracle injection (AD-568a/AD-620) are not tool calls. A claim built on them gets the sentence, which stays true ("through a tool").
- **L4:** English only, with the listed past-tense forms. Single quotes are not masked. Paraphrases ("I had a look") are not found.
- **L5:** unchecked paths: group replies, federated turns, AD-272 cache replays, AD-1230 held-turn replays and AD-1165 promoted-run reports, which carry no record or bypass the pipeline.
- **L6:** a reply longer than about 410 characters loses the sentence from its stored episode (`[:500]`).
- **L7:** in a multi-pass turn where an earlier pass called nothing and a later pass called only unverifiable-id tools, the earlier empty record stays (`cognitive_agent.py:153-161`), so the check fires. A pass with no call usually ends the turn.
- **L8:** the AD-1357 journal row hashes the output before the pipeline, as it does for every pipeline rewrite.
- **L9:** the claim stays in the reply. Removing it is S3.

**F1 (a follow-up item, not S2):** step 1 adopts a retry's reply but keeps the first attempt's `ctx.tool_invocations` (`reply_pipeline.py:703-707` versus `:183`). So the write-claim guard judges a retried reply against the first attempt's record. S2 abstains there. The write side needs its own item; the orchestrator files it.

## 12. Acceptance criteria

- The two live sentences, on a turn with an empty tool record, run through the real chain and `run()`: they end with `LOOKUP_DISCLOSURE` in the reply, the response and the episode, and a WARNING names the claim.
- A turn whose lookup ran, a turn whose only call is unverifiable, the switch off, an in-reply read, an adopted retry and the Captain's own words leave the reply unchanged.
- The 16 wordings that are not claims are not found.
- Every mutation row is killed by its named killer.
- The focused gate and the broad gate pass. `gen_config_reference.py --check` passes.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 13. #1750 landing comment (the orchestrator fills `<...>`)

> AD-1358 S2 is merged (#<PR>, merge `<sha>`). Gate: <result>.
>
> **What S2 does:** on a 1:1 DM turn whose agentic loop called no tool, a reply whose own wording claims a search or a record lookup ("I searched", "the record I found", "the Ship's Records search turned up", "my search shows") ends with one sentence: "[This turn's tool record is empty: no search or lookup was run through a tool on it.]". The turn log names the claim at WARNING. The tool record decides and the wording only selects the turn; the reply's own words stay. It sits under `write_claim_guard.enabled` (on by default). Measured by `tests/test_ad1358_s2_lookup_claim.py` (45 cases, including the two sentences of 2026-11-04); mutation census <...>.
>
> **What stays for S3:** claims about shared history ("last time you beat me"), the extraction and revision pass, this issue's DM acceptance (no such claim in the reply, the log naming the dropped claim) and the BF-741 check on a retracted claim.
>
> **Not checked by S2:** a turn that called any tool; group, federated, cached, replayed and promoted-run replies (contract section 11, L1 to L9).
>
> **Follow-up:** <the F1 issue number>: the write-claim guard judges a retried reply against the first attempt's tool record.
>
> #1750 remains for S3.

## 14. Results on the oracle trees (the orchestrator, 2026-11-25)

The base oracle is a clean detached tree at the Base above (`8704d194`, which is `ad28bc34` plus B13); the candidate is a second tree at the same commit with the source and test pairs of section 6 applied by `contract_tools.py` (P1-1 to P1-9, P2-1 to P2-3 and the two new files; every SEARCH occurred once at its turn; `ws_ambiguity.py`: 0 hazards; `git diff --check` clean). The tracker pairs P3-1 and P3-2 were applied to a third tree at the Base (14.6). Every check, baseline, census row and focused run below was first made on `ad28bc34`, the tree the draft was made on, before B13 merged, and again on the Base, with the same results (the census table and the pinned hashes are identical). B13 changed none of the source or test files of the pairs: `git diff --name-only ad28bc34 8704d194` lists 16 files, and only `PROGRESS.md`, `DECISIONS.md` and the ledger pair overlap this contract's files. The rows ran with `bf1358_s2_rows.py` and the focused runs with `run_focused.py` (both outside the repository): one pytest process per selector, `-n 0 -p no:randomly` (the random order only where named), `HOME` and `USERPROFILE` redirected to an empty directory (empty afterwards), the cases read from the JUnit file.

### 14.1 Checks 1 to 6 of section 8, on `8704d194`

- Check 1: all 14 pairs matched exactly once. Check 2: no hits.
- Check 3: three lines, the draft's list unchanged.
- Check 4 (`b14_check4_probe.py`): for a turn whose only call has the id `None` and no result, the Base returns `ToolInvocations(attempted=(), succeeded=())` and the candidate returns `None`. For a turn with no call (`ToolInvocations(attempted=(), succeeded=())`) and for a turn with one correlated call and no result (`ToolInvocations(attempted=('oracle_query',), succeeded=())`), both trees return the same value, and the AD-1295 log line about an uncorrelatable id is the same on both.
- Check 5: the new test file copied onto the Base gives 1 collection error, `ModuleNotFoundError: No module named 'probos.cognitive.dm.lookup_claim'`.
- Check 6: `gen_config_reference.py --check` on the clean Base exits 0. On the candidate it exits 1 (stale) before regeneration and 0 after `gen_config_reference.py`, which changes one line of `docs/development/config-reference.md`: the description of `write_claim_guard.enabled`.

### 14.2 Candidate runs

- Baselines on the candidate, one process each: the new test file 45 passed (13 functions); `test_ad1295_tool_success_ledger.py` 61 passed; `test_ad1285_write_claim_guard.py` 58 passed.
- The focused command of section 8 (22 files), `-n 0`: 1119 passed in the given order (115.7 s), in reverse (109.5 s) and in the default random order (108.0 s). On `ad28bc34` the same command gave 1119 passed in each order.

### 14.3 Mutation census (the campaign of record)

Run once on the candidate overlay (the Base plus the source and test pairs of section 6), one mutant at a time, each file restored byte for byte. **19 of 19 killed**, each by the killers that the table of section 8 names; the table below lists the named killers that failed (file = `tests/test_ad1358_s2_lookup_claim.py`, ad1295 = `tests/test_ad1295_tool_success_ledger.py`).

| ID | Verdict | Killed by |
|---|---|---|
| LC-1 | KILLED | file: `test_the_record_decides[lookup-ran, lookup-failed, other-tool]`; file: `test_a_lookup_that_ran_leaves_the_reply_byte_identical` |
| LC-2 | KILLED | file: `test_the_record_decides[look-alike]` |
| LC-3 | KILLED | file: `test_the_record_decides[incomplete-not-a-bool]` |
| LC-4 | KILLED | file: `test_the_record_decides[incomplete]`; file: `test_a_mesh_read_in_the_reply_makes_the_check_abstain`; file: `test_an_action_marker_in_the_reply_makes_the_check_abstain`; file: `test_an_adopted_retry_makes_the_check_abstain` |
| LC-5 | KILLED | file: `test_wording_that_is_not_a_claim_is_not_found[quoted, curly-quoted, backticks, block-quote]` |
| LC-6 | KILLED | file: `test_wording_that_is_not_a_claim_is_not_found[if, question]` |
| LC-7 | KILLED | file: `test_wording_that_is_not_a_claim_is_not_found[memory]` |
| LC-8 | KILLED | file: `test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed[record-i-found]`; file: `test_claim_wording_is_found[record-i-found]` |
| LC-9 | KILLED | file: `test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed[record-i-found, records-search]`; file: `test_a_write_disclosure_and_a_lookup_disclosure_compose` |
| LC-10 | KILLED | file: `test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed[record-i-found, records-search]` |
| LC-11 | KILLED | file: `test_a_write_disclosure_and_a_lookup_disclosure_compose` |
| LC-12 | KILLED | file: `test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed[record-i-found, records-search]`; file: `test_the_captains_words_are_never_read` |
| LC-13 | KILLED | file: `test_the_write_claim_switch_turns_the_lookup_check_off` |
| LC-14 | KILLED | file: `test_an_adopted_retry_makes_the_check_abstain` |
| LC-15 | KILLED | file: `test_an_action_marker_in_the_reply_makes_the_check_abstain` |
| LC-16 | KILLED | file: `test_a_mesh_read_in_the_reply_makes_the_check_abstain` |
| LC-17 | KILLED | file: `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed`; ad1295: `test_unverifiable_call_is_omitted_from_attempted[null, empty, non-string-int, non-string-list]`; ad1295: `test_duplicate_call_ids_are_uncorrelatable` |
| LC-18 | KILLED | ad1295: `test_uncorrelatable_call_does_not_hide_its_well_formed_sibling` |
| LC-19 | KILLED | file: `test_the_disclosure_is_ascii_and_not_a_capability_gap` |

Pinned files, as they stand in the oracle's working copy (sha256, and the git blob id that `git hash-object --path` gives under autocrlf; the census restored each of the first five byte for byte):

| File | sha256 | Blob id |
|---|---|---|
| `src/probos/cognitive/agentic_dispatch.py` | `8c047f5b7755d1bbde7b707f7c9d40f7ff1845ac9f2ed870d9e086b12299dac3` | `d02fc3e583f959bace4c0f400fe4626dfd086a5b` |
| `src/probos/cognitive/dm/lookup_claim.py` | `dcea541baf9ed653a9fe8f59c6fc32227692f25446083ba5ab139f50e999f0e7` | `d04e7becb26f64dbf09e52cc6920e07adc0e8279` |
| `src/probos/cognitive/dm/reply_pipeline.py` | `a6e47293d6ad02c0c4fdc2a193b2540aa589ca683f0fc28fdcf31a53202a887a` | `ea4700ce562dd7caf2165de4039e4015e6753881` |
| `src/probos/config_models/agentic.py` | `6aa0b10a1c5038f4793f3bb62867abb1a78fb458d8313bc3e9675ceb17cd4a88` | `9af2cab4fbaa2b2a1d01b841ebbe236478c4b663` |
| `tests/test_ad1295_tool_success_ledger.py` | `7508f54ccf612b9262313fc6e817f6b50e3d48aced058895451b33087de55a3b` | `1bdaa741495c6d0fc7f05a21a596c47ff98d5537` |
| `tests/test_ad1358_s2_lookup_claim.py` | `2adfd333dcde673efc9858155e30b259381519f2d3b9e6cece17cde1216329a0` | `d78b152c8f0263bfeb93e0fb5ded80c8ac098e3e` |
| `docs/development/config-reference.md` (regenerated) | `3b37dad80cbe0896d0687475e3953408173b253be9b8232f217adfba3230aa9d` | `47ba27ac1dd9130f192988f54fd858cce69a985c` |

### 14.4 What the vessel's own data shows (read only; Evidence Standard)

Both reads opened the stores read only (`mode=ro&immutable=1` for the database; the attachment blobs as bytes), printed aggregates only and left every file unchanged (the database's size and mtime were the same before and after).

- **How often the draft's patterns fire** (`live_claim_rate.py`, over `chat_threads.db` under the vessel's data directory): 632 agent replies, 2026-06-09 to 2026-11-24. `find_lookup_claim` finds a claim in 4 of them (0.6%): one of 2026-06-14, one of 2026-07-27 and the two of 2026-11-04. 83 further replies mention search or record words and are not claims. 342 of the 632 replies are longer than 410 characters, so for them the appended sentence falls outside the 500-character snapshot that the episode stores (limit L6).
- **What the persisted tool trace says** (`live_trace_refs.py`): 200 of the 632 agent replies carry a `tool_trace_ref`, with 30 distinct refs. 171 of them are `4f53cda18c2b...`, the sha256 of the two bytes `[]`, and its blob in the attachments directory is a JSON array of 0 entries. All six agent replies of 2026-11-04 carry that ref, so the two sentences of the live case were sent on a turn with an empty tool trace, as the issue reported. The two older matches (2026-06-14, 2026-07-27) carry no trace: a turn with no record, on which the check abstains.

### 14.5 Finding F1 of section 11, reproduced on the clean base (recorded, not repaired here)

Step 1 adopts a retry's reply and keeps the first attempt's `ctx.tool_invocations`, so `step_4n` and `step_4m` judge the retry's reply against the first attempt's record. Reproduced with `repro_f1_retry_record.py` on the clean base: real `DmReplyPipeline` steps over a real `DmReplyContext` (the AD-1295 test helper), the real `DmSanityGate` and real `IntentResult` metadata; only the intent bus is a stand-in. The same scenarios ran through the whole `DmReplyPipeline.run()` with the same result.

- Control (no retry, the first attempt wrote nothing): the guard discloses, so the probe discriminates.
- A: the first attempt failed to write; the retry's own record shows a successful write and its reply says so. The guard still appends "A durable write was attempted on this turn and did not ..." (a false disclosure).
- B: the first attempt wrote; the retry's own record shows a failed write and its reply claims a save. The guard abstains (a missed disclosure).
- In both, `ctx.tool_invocations` after the retry is still the first attempt's record.

Severity P3, rare (an adopted retry on a turn whose two attempts disagree about a write), ordinary reach. S2 makes its own check abstain after an adopted retry (`lookup_record_incomplete`, section 2) and does not change the write verdict. The orchestrator files F1 as an item of the follow-up issue #1820.

### 14.6 Tracker milestone (M3) on the Base

P3-1 and P3-2 were applied by the tool to a third tree at the Base (each SEARCH occurred once at its turn, `ws_ambiguity.py` reported 0 hazards and `git diff --check` was clean; the census sentence in P3-1 is the one of 14.3), then `scripts/gen_ad_ledger.py -P` (no `--online`) ran. `gen_ad_ledger.py --check` reported the report stale (exit 1) after the two tracker pairs and current (exit 0) after the regeneration. The regeneration changed `docs/development/ad-ledger-snapshot.json` in three fields only (`captured_at`, `head` `8704d194`, `subject_count` 4554 to 4558) and `docs/development/open-ads-report.md` in its snapshot line and in the line numbers of two PROGRESS.md notes (1777 to 1779 and 1783 to 1785). The report holds no AD-1358 row before or after, so no ledger status changes. In the real tree the regeneration runs at M3 on the M2 commit, so its head and subject count differ from these.

## 15. Amendment A1 (found by the preflight before review: the configuration facade baseline)

**Finding.** `scripts/run_test_gate.py --preflight-only --label ad-1358-s2` on the frozen head `ae1a1a94` stopped after 12.6 s: `scripts/check_config_facade.py --check` reported 2 problems, `facade-schema-digest: SystemConfig 11122e41... -> 1b59da8e...` and `facade-schema-digest: WriteClaimGuardConfig f52a9886... -> ecb38aa2...` ("a type or constraint changed"). The baseline `docs/development/config-facade-baseline.yaml` pins a digest of each model's JSON schema, and the schema holds the field descriptions, so the corrected description of `write_claim_guard.enabled` (P1-9, decision D5) changes the `WriteClaimGuardConfig` digest and, because `SystemConfig` nests it, the `SystemConfig` digest. The draft's sections 7 and 8 did not list the baseline, and its section 2 weighed the AD-1152 default-config digest and the `test_ad1270e2i_agentic_models.py` pins only for a rejected new field. The checks of section 14 ran `gen_config_reference.py --check` and not the facade check, so neither the draft nor the oracle runs could see it.

**Repair (the orchestrator; no Builder, no pair).** `scripts/check_config_facade.py --update-baseline`, the artifact's own regeneration command, rewrote the baseline. The diff is exactly two `schema_sha256` lines, the digests above each moved to its new value, and `--check` then passes (names=310, owned=297, incidental=13, models=229, fields=1886). On the oracle `ob14m` and in the build tree the regenerated file has the same blob id, `2f0f1149082146b14ae0efe5545da0dd36cc32b3`. The AD-1152 default-config digest (`tests/fixtures/ad1152_agentic_off_golden.json`, `default_config_sha256`) hashes the default values and not the descriptions: `tests/test_ad1152_agentic_correlation.py` and `tests/test_ad1270b_architecture_fitness.py` pass on the candidate (104 passed).

**Milestone M4.** Subject: `The configuration facade baseline records the corrected write-claim description`. Path: `docs/development/config-facade-baseline.yaml`.

**Check 7 (added to section 8).** `scripts/run_test_gate.py --preflight-only --label ad-1358-s2` on the staged candidate (M0 to M4): exit 0 in 48.0 s (the configuration facade, the ledger, the seam contracts, the architecture principles, the store registry and `compileall`).

**Property 12 (added to section 9).** The baseline differs from its base by exactly the two `schema_sha256` lines of `SystemConfig` and `WriteClaimGuardConfig`, and `check_config_facade.py --check` exits 0.
