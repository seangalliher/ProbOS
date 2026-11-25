# AD-1358 S2 (#1750): a 1:1 reply that claims a search or lookup is checked against the turn's tool record

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24
**Assembled by:** the orchestrator, 2026-11-25: the heading and pair layout follow what `contract_tools.py` reads; the Status and Base lines follow B13's merge; the Architect's text is otherwise unchanged, except what section 14 records.
**Status:** ready to build; B13 (BF-992, #1324) has merged. **Owning issue:** #1750 (slice S2 of the Architect's ranking, comment 3). Commits and the PR say `Refs #1750.` #1750 stays open for S3.
**Base:** `8704d19468797991298f471ecdf4b7cef3797b88` (origin/main after B13 (BF-992, #1324) merged; the draft was made on `ad28bc34`). B13 shared only `PROGRESS.md`, `DECISIONS.md` and the ledger pair with this item. P3-1 and P3-2 anchor on text that exists on both trees.
**Number:** AD-1358 (a slice; no new number).
**Line endings:** the working copies are CRLF and the blocks below are LF. Every SEARCH starts at a line start and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 45 new cases in 13 functions (one new file); 3 functions in `tests/test_ad1295_tool_success_ledger.py` updated; 0 removed. Amendment A2 (section 16): 46 new cases in 15 functions (a second new file, `tests/test_ad1358_s2_a2_repairs.py`); the first new file gains 2 cases and 1 updated function (47 cases); the same 3 functions of `test_ad1295` updated again; 0 removed.
**Scope:** new `src/probos/cognitive/dm/lookup_claim.py`; `cognitive/dm/reply_pipeline.py`, `cognitive/agentic_dispatch.py`, `dm_reply.py` (`ToolInvocations.incomplete`, amendment A2), `config_models/agentic.py` (docstring and description only); `docs/development/config-reference.md` (regenerated); one new test file; one updated test file; the trackers.

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
    - outside fenced blocks (only with their closing fence), paired double quotes, curly quotes and backticks (over line breaks, not over a blank line) and `>` block quotes (amendment A2);
    - not after `if`, `whether`, `unless`, `have`, `had`, `did`, `not`, `never` or `n't`;
    - not about the agent's memory.
  - `assess_lookup_claim(text, invocations, *, record_incomplete)` returns that claim only when `type(invocations) is ToolInvocations` with empty `attempted` and `succeeded` and `incomplete` False (amendment A2), and `record_incomplete is False`.
- **In `step_4m`:**
  - After the write verdict, the claim is assessed on `pre_write_disclosure_body`.
  - On a claim, `LOOKUP_DISCLOSURE` is appended after any write sentence, and one WARNING names the claim.
  - `write_disclosure_suffix` holds both sentences.
  - The check sits under the existing `write_claim_guard.enabled`.
- **The `DmReplyContext.lookup_record_incomplete` flag:**
  - Set by step 1 when it dispatches a retry, before the send and whatever the retry returns, because the reply keeps the first attempt's record and the retry may have run tools (amendment A2; the draft set it only on adoption).
  - Set by step 4e when it parses `[ACTION:]` envelopes, and by step 4h when it parses a `[MESH ...]` tag. Those reads run outside the record.
- **`_project_tool_invocations`** marks the record `incomplete` when it drops a call whose id is unverifiable; `ToolInvocations.merged_with` ORs the mark and the wire carries it only when true (amendment A2; the draft returned `None`, which the pass fold skips).
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
| D6 | **A record that left a call out says so** (amendment A2, D10): `ToolInvocations.incomplete`, set by `_project_tool_invocations` when it drops an unverifiable call, ORed by `merged_with`, on the wire only when true. The lists are unchanged, so the write verdict is unchanged (`step_4n` reads `attempted` only) and `agent_work_runner.py:384-388` records the same `tools`. The draft's `None` was replaced: the pass fold skips a `None` pass, so a later empty pass restored "called no tool" (R1-2). |
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
- `ToolInvocations`: one defaulted field, `incomplete`, on the wire only when true; `_project_tool_invocations` sets it when it drops a call (D6, amendment A2).
- Step 1: the flag is set whenever a retry is dispatched (D9, amendment A2).
- The `write_claim_guard.enabled` description.
- One new WARNING log line.
- No event or journal field. One optional wire key, `incomplete`, present only when true (amendment A2).

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
| `ToolInvocations.incomplete` (amendment A2) | `reply_pipeline.py:2410-2415` (`step_4n` reads `attempted`); `agent_work_runner.py:384-388` (`succeeded`); `cognitive_agent.py:142-161` (fold: `merged_with` ORs it), `:102-122` (forwarded on `is not None`), `:298-312` (`to_wire`), `:6801-6803` (`act()` copy), `:79-99` (AD-272 strip); `routers/agents.py:3838` (the only reconstruction); `dm_reply.py:616-690` (wire) | Same lists, write verdict and work-item result for every input (D6); a complete record's payload is byte-identical; federation, the HXI and `scripts/` read no `tool_invocations` |
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
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1358_s2_lookup_claim.py tests/test_ad1358_s2_a2_repairs.py tests/test_ad1295_tool_success_ledger.py tests/test_ad1285_write_claim_guard.py tests/test_ad1293_turn_record_reaches_episode.py tests/test_bf866_artifact_channel_seams.py tests/test_ad933_group_chat_escalation.py tests/test_ad1156_plan_mode_reply_tags.py tests/test_ad1156_plan_mode_side_effects.py tests/test_ad1156_plan_mode_containment.py tests/test_ad1156_plan_mode_learning.py tests/test_ad934_deliberate.py tests/test_ad1192_owned_steps_dm.py tests/test_ad726_dm_reply_pipeline.py tests/test_ad869_mesh_read_inline.py tests/test_ad745_pipeline_dispatch.py tests/test_ad724_dm_sanity_gate.py tests/test_ad724_dm_hardening.py tests/test_ad1162_captain_session_binding.py tests/test_ad856_agentic_dispatch.py tests/test_ad1270e2i_agentic_models.py tests/test_config_reference_current.py tests/test_ad1343_stop_seam_inventory.py -q -n 0
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
| LC-17 | P1-8 deleted (superseded by amendment A2, which replaces those lines; see A2-M5) | `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed`; `test_ad1295::test_unverifiable_call_is_omitted_from_attempted`, `::test_duplicate_call_ids_are_uncorrelatable` |
| LC-18 | P1-8 condition becomes `if dropped:` (superseded by amendment A2; see A2-M4) | `test_ad1295::test_uncorrelatable_call_does_not_hide_its_well_formed_sibling` |
| LC-19 | Sentence reworded to contain "no tool" | `test_the_disclosure_is_ascii_and_not_a_capability_gap` |

## 9. Diff Reviewer: properties to verify

1. The lookup sentence is appended only when all of these hold: `type(ctx.tool_invocations) is ToolInvocations` with empty `attempted` and `succeeded` and `incomplete` False; `lookup_record_incomplete is False`; `write_claim_guard.enabled` is on; and a claim is found. Every other path leaves the reply byte-identical.
2. The sentence is true of every turn it is appended to, whatever wording matched. It names the record, not the agent's words.
3. The write verdict, its log line and its sentence are unchanged for every ledger. When both apply, the write sentence comes first and `write_disclosure_suffix` holds both. `pre_write_disclosure_body` still holds the body before both.
4. `_project_tool_invocations` lists the same names as on the Base for every input, marks the record `incomplete` exactly when it dropped a call, and returns `None` only when it raises (amendment A2). The write ledger's consulted set is identical for every input.
5. The checker reads only the reply body passed by `step_4m`, never `req_message` or `message_text`.
6. `_full_steps`, `_escalation_steps` and the three plan-mode sets are unchanged. `DmReplyPipeline` gains no method.
7. The flag is set in step 1 whenever a retry is dispatched (before the send, for every outcome: adopted, empty text, None, no response, a raise) and never when none is (amendment A2), in 4e only when envelopes were parsed, and in 4h only when a tag was parsed.
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
- **AD-1269:** `None` versus empty. Adopted; a record that left out an unverifiable call says so with `incomplete` rather than becoming `None` (D6, amendment A2).
- **AD-1242:** the crew verifier gives the model "the agent's tool trace, not its narration" (`crew_verifier.py:1405`). Same principle, deterministic here.
- **BF-922 `output_grounding.py`:** rejected as the home (section 2).
- **AD-981b and AD-979b:** they cover answers to questions; claims the agent volunteers go to S3.

**Recorded limits (blind spots):**
- **L1:** a lookup made on an earlier turn and cited now gets the sentence. The sentence remains true of this turn.
- **L2:** a turn with any tool call (for example only `publish_finding`, or a lookup that failed) is not checked.
- **L3:** passive recall and Oracle injection (AD-568a/AD-620) are not tool calls. A claim built on them gets the sentence, which stays true ("through a tool").
- **L4:** English only, with the listed past-tense forms. Single quotes are not masked. Paraphrases ("I had a look") are not found. A quote or backtick span is masked over line breaks but not over a blank line, and a fence only with its closing fence; an unpaired quote can still pair with a later one in the same paragraph and hide a claim between them (the sentence is then missed, never false).
- **L5:** unchecked paths: group replies, federated turns, AD-272 cache replays, AD-1230 held-turn replays and AD-1165 promoted-run reports, which carry no record or bypass the pipeline.
- **L6:** a reply longer than about 410 characters loses the sentence from its stored episode (`[:500]`).
- **L7 (amendment A2; the earlier text named a case A2 removes):** a pass whose projection raises carries no record, and the pass fold skips it, so a later empty pass can stand for the turn. The projection reads plain attributes and has no known trigger. An unverifiable id, the reachable case, now marks the record `incomplete` in every pass order.
- **L8:** the AD-1357 journal row hashes the output before the pipeline, as it does for every pipeline rewrite.
- **L9:** the claim stays in the reply. Removing it is S3.

**F1 (a follow-up item, not S2):** step 1 adopts a retry's reply but keeps the first attempt's `ctx.tool_invocations` (`reply_pipeline.py:703-707` versus `:183`). So the write-claim guard judges a retried reply against the first attempt's record. S2 abstains there. The write side needs its own item; the orchestrator files it.

## 12. Acceptance criteria

- The two live sentences, on a turn with an empty tool record, run through the real chain and `run()`: they end with `LOOKUP_DISCLOSURE` in the reply, the response and the episode, and a WARNING names the claim.
- A turn whose lookup ran, a turn any of whose passes called a tool with an unverifiable id (in any pass order), the switch off, an in-reply read, a dispatched retry (whatever it returned) and the Captain's own words leave the reply unchanged; a reply the gate accepts is still checked.
- The 16 wordings that are not claims are not found, nor are the six wordings quoted or fenced over several lines (amendment A2); the four unquoted controls beside a fence or a quote are found.
- Every mutation row is killed by its named killer.
- The focused gate and the broad gate pass. `gen_config_reference.py --check` passes.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 13. #1750 landing comment (the orchestrator fills `<...>`)

> AD-1358 S2 is merged (#<PR>, merge `<sha>`). Gate: <result>.
>
> **What S2 does:** on a 1:1 DM turn whose agentic loop called no tool, a reply whose own wording claims a search or a record lookup ("I searched", "the record I found", "the Ship's Records search turned up", "my search shows") ends with one sentence: "[This turn's tool record is empty: no search or lookup was run through a tool on it.]". The turn log names the claim at WARNING. The tool record decides and the wording only selects the turn; the reply's own words stay. It sits under `write_claim_guard.enabled` (on by default). Measured by `tests/test_ad1358_s2_lookup_claim.py` (47 cases, including the two sentences of 2026-11-04) and `tests/test_ad1358_s2_a2_repairs.py` (46 cases: a retry whatever it returns, an unverifiable call in any pass order, quotes and fences over several lines, masking in linear time); mutation census <...>.
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

### 14.7 Amendment A2: results on the oracle trees (the orchestrator, 2026-11-25)

The A2 overlay is a clean detached tree at the frozen head `102e8b33` with the source and test pairs of section 16 applied by `contract_tools.py` (A2-1 to A2-15, A2-19 to A2-21 and the new file of 16.5); the tracker pairs A2-16 to A2-18 were applied to a second tree at the head (14.7.4). The pre-repair tree is a clean tree at `102e8b33`. The rows ran with `bf1358_a2_rows.py` (outside the repository; the runner of the first census with the A2 rows) and the focused runs with `run_focused.py`, as in section 14.

#### 14.7.1 Checks 8 to 10 of section 16

- Check 8: all 21 pairs matched exactly once at their turn (A2-20 and A2-21 edit the new file of 16.5), `ws_ambiguity.py`: 0 hazards, `git diff --check` clean.
- Check 9: `gen_config_reference.py --check` and `check_config_facade.py --check` exit 0 with no regeneration (names=310, owned=297, incidental=13, models=229, fields=1886).
- Check 10: the A2 test file copied onto the pre-repair head gives 1 collection error, `ImportError` for `_mask_quoted` (A2-20 imports it). On the first draft of the file, before A2-20 and A2-21, 27 of its 39 cases failed on the pre-repair head, and the 12 that passed were the controls (the adopted retry, a reply the gate accepts, the complete wire shape, the four malformed `incomplete` keys, the unquoted controls beside a fence or a quote).

#### 14.7.2 Candidate runs

- Baselines on the A2 overlay, one process each: the first test file 47 passed, `test_ad1295_tool_success_ledger.py` 61, `test_ad1285_write_claim_guard.py` 58, the A2 file 46.
- The focused command of section 8 (23 files, with the A2 file), `-n 0`: 1167 passed in the given order (143.6 s), in reverse (102.8 s) and in the default random order (103.6 s). Without the A2 changes the 22-file command gave 1119 in each order (14.2).

#### 14.7.3 The scaling measurement that changed A2-6 (found by the orchestrator before round 2)

Property 15 of the first A2 text says no alternative of the masking can backtrack super-linearly. The orchestrator measured it with `probe_quoted_scaling.py` (outside the repository): `find_lookup_claim` on n lines of one family plus an unquoted claim, n doubling from 500 to 8,000, with a control of plain lines that scales by 2.0 per doubling.

- The first draft of A2-6 (one regex) was quadratic on unclosed fence openers: 8,000 lines of three backticks and a letter (40,045 characters) took 1,831 ms and 8,000 lines of three tildes and a letter 3,154 ms, about four times per doubling. Unpaired double quotes, unpaired backticks and a single long fence stayed linear (3 to 9 ms).
- The same probe on the head before A2 (`102e8b33`) showed that the single-line curly alternative of the first built version was already quadratic: 8,000 unpaired curly quotes on one line (24,045 characters) took 611 ms, 5.8 times at the last doubling. The Architect had derived this from the regex; the measurement confirms it.
- The redraft of A2-6 (a two-pass scanner, decision D11) is linear on every family: 12.6 ms (backtick fences) and 5.8 ms (tilde fences) at 8,000 lines, 4.1 ms (curly quotes in one paragraph), 11.0 ms (curly quotes separated by blank lines) and 43.6 ms for a mixed family of 184,045 characters; each family doubles by 2.0 to 2.5. The scaling guards of A2-21 pin it (16.10).

#### 14.7.4 Tracker pairs

A2-16 to A2-18 were applied by the tool to a second tree at the head (each SEARCH occurred once at its turn, `ws_ambiguity.py`: 0 hazards, `git diff --check` clean). `gen_ad_ledger.py --check` exited 0 after the tracker pairs and 0 after `gen_ad_ledger.py -P` rewrote the snapshot and the report: the amendments change no ledger status. In the real tree the regeneration runs at M7 on the M6 commit, so its head and subject count differ from these.

The mutation census of A2 (A2-M1 to A2-M25) and its pinned files are in 16.10.

## 15. Amendment A1 (found by the preflight before review: the configuration facade baseline)

**Finding.** `scripts/run_test_gate.py --preflight-only --label ad-1358-s2` on the frozen head `ae1a1a94` stopped after 12.6 s: `scripts/check_config_facade.py --check` reported 2 problems, `facade-schema-digest: SystemConfig 11122e41... -> 1b59da8e...` and `facade-schema-digest: WriteClaimGuardConfig f52a9886... -> ecb38aa2...` ("a type or constraint changed"). The baseline `docs/development/config-facade-baseline.yaml` pins a digest of each model's JSON schema, and the schema holds the field descriptions, so the corrected description of `write_claim_guard.enabled` (P1-9, decision D5) changes the `WriteClaimGuardConfig` digest and, because `SystemConfig` nests it, the `SystemConfig` digest. The draft's sections 7 and 8 did not list the baseline, and its section 2 weighed the AD-1152 default-config digest and the `test_ad1270e2i_agentic_models.py` pins only for a rejected new field. The checks of section 14 ran `gen_config_reference.py --check` and not the facade check, so neither the draft nor the oracle runs could see it.

**Repair (the orchestrator; no Builder, no pair).** `scripts/check_config_facade.py --update-baseline`, the artifact's own regeneration command, rewrote the baseline. The diff is exactly two `schema_sha256` lines, the digests above each moved to its new value, and `--check` then passes (names=310, owned=297, incidental=13, models=229, fields=1886). On the oracle `ob14m` and in the build tree the regenerated file has the same blob id, `2f0f1149082146b14ae0efe5545da0dd36cc32b3`. The AD-1152 default-config digest (`tests/fixtures/ad1152_agentic_off_golden.json`, `default_config_sha256`) hashes the default values and not the descriptions: `tests/test_ad1152_agentic_correlation.py` and `tests/test_ad1270b_architecture_fitness.py` pass on the candidate (104 passed).

**Milestone M4.** Subject: `The configuration facade baseline records the corrected write-claim description`. Path: `docs/development/config-facade-baseline.yaml`.

**Check 7 (added to section 8).** `scripts/run_test_gate.py --preflight-only --label ad-1358-s2` on the staged candidate (M0 to M4): exit 0 in 48.0 s (the configuration facade, the ledger, the seam contracts, the architecture principles, the store registry and `compileall`).

**Property 12 (added to section 9).** The baseline differs from its base by exactly the two `schema_sha256` lines of `SystemConfig` and `WriteClaimGuardConfig`, and `check_config_facade.py --check` exits 0.

## 16. Amendment A2 (review round 1: R1-1, R1-2, R1-3)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-25

**Finding.** Review round 1 (`gpt-6.1-sol`) on the frozen head `102e8b33` returned REQUEST CHANGES with three findings, each a regression of this change with ordinary reach. The orchestrator reproduced each one first-hand (`repro_b14_r1_findings.py`: the real `DmReplyPipeline.run()`, the real `DmSanityGate`, the projection, the pass fold and the metadata builder; only the intent bus is a stand-in), and the controls discriminate:
- **R1-1 (P2).** Step 1 set `lookup_record_incomplete` only on an adopted retry. A retry that ran a lookup and returned empty text or None, or whose dispatch raised, left the first attempt's empty record standing, so the sentence was appended although the retry may have run a lookup.
- **R1-2 (P2).** P1-8 made a pass whose every call was unverifiable `None`, and `_accumulate_pass_invocations` skips a `None` pass. An unverifiable pass followed by a tool-free pass delivered an empty record, so the check fired on a turn that called a tool. L7 named only the reverse order, and the check fired there too.
- **R1-3 (P3).** `_QUOTED` stopped at a newline, so a fenced block or a double-quoted example spanning several lines was read as the agent's own claim.

**Vessel logs** (the six rotated `probos.log*` files, 2026-07-29 to 2026-11-24): 0 lines of the AD-1295 uncorrelatable-id warning, 0 adopted-retry lines and 0 retry-dispatch failures, against 263 other AD-724 lines. The triggers of R1-1 and R1-2 have not occurred on this vessel in that window; their reach is by code path. Every finding is repaired here. F1 stays the #1820 item. A measurement before round 2 found the first draft of A2-6 quadratic on unclosed fence lines (8,000 lines of three backticks and a letter: 1.8 s; of three tildes and a letter: 3.2 s; about four times per doubling), a regression of A2-6. Reading the regex showed the same for unpaired opening curly quotes (derived, not measured). A2-6 is redrafted as a linear pass (D11), and A2-19 to A2-21 are added.

**Decisions (continuing section 3).**

| # | Decision |
|---|---|
| D9 | **Step 1 sets the flag when it dispatches a retry**: before the send, for every outcome (adopted, empty text, None, no response, a raise). A retry is a second run of the agent and may call tools whatever it returns, while `ctx.tool_invocations` stays the first attempt's record in every case. Abstaining on a raise is the safe side: a timed-out dispatch may have run tools. A gate that accepts the reply dispatches nothing and leaves the flag False. F1 (#1820) is unchanged. |
| D10 | **The record says when it left a call out.** `ToolInvocations` gains `incomplete: bool = False`. `_project_tool_invocations` sets it when it drops a call whose id is unverifiable, whether or not other calls are listed. `merged_with` ORs it. `to_wire` emits `"incomplete": true` only when it is set, and `from_wire` accepts the key only with the value `true`. `assess_lookup_claim` abstains unless it is exactly False. The flag rides the record through every hop the record already takes (the pass fold, `_attach_run_provenance`, the `act()` copy at `cognitive_agent.py:6801-6803`, `_build_result_metadata`, the route), and the AD-272 cache strips it with the record. So no new key, field or route change is needed, and `cognitive_agent.py` is untouched. The lists do not change, so `step_4n` (reads `attempted`), `agent_work_runner` (reads `succeeded`) and the write verdict are unchanged for every input. P1-8's `None` is replaced: `None` again means only that the pairs were not read (`agentic_dispatch.py:2465-2469`) or that the projection raised (L7). Rejected: a sticky observation key plus a second metadata key (two facts that must travel together over five hops, a route change, and a new outcome field to tell "dropped" from "never ran"); a `None` pass absorbing the union (loses known write evidence, so a failed save would go undisclosed); keeping `None` and making the fold remember it (the fold cannot tell an unreadable pass from one whose loop never ran). |
| D11 | **Quoted wording over several lines is masked, bounded by the paragraph.** A fenced block (three or more backticks or tildes at a line start) is masked only together with its closing line: the first later line made only of the same fence character, at least as many, and spaces. Paired double quotes, paired curly quotes and backtick spans may run over line breaks but not over a blank line. A stray quote can hide at most the rest of its paragraph, and an unclosed fence hides nothing. The two errors are not symmetric: a missed mask appends a sentence that is still true of the record (D1) and logs quoted words as a claim, while a wide mask drops a true disclosure. Rejected: a character cap (arbitrary; it cuts real examples); masking to the end of the text after an unclosed fence (a stray fence would hide every later claim); guessing which unpaired quote is stray (no reliable signal); one regex for all of it (its fence alternative rescanned the rest of the text from every unclosed opener and its curly alternative from every unpaired opener: quadratic, measured at 1.8 s and 3.2 s on about 40 KB of unclosed fence lines before round 2). The masking is a line pass for fences (a backward pass records the longest closing line of each fence character after every line, so an opener without one costs one lookup) and one forward pass for quotes, backticks and block quotes (a failed search proves that no opener of its kind remains before the paragraph break, and a failed curly search marks the paragraph): linear in the text's length (A2-6, A2-19). A span may still run into a fenced block, as with the single regex. Internal prior art: BF-866b `_fence_spans` (`artifact_extractor.py:358-392`) uses the same closing rule and the opposite tail rule (an unclosed fence runs to the end), because on the write side the wide mask is the safe one. |
| D12 | **Round 2 reviews the whole candidate** (`8704d194` to the A2 head), not the delta. A2 changes shared contracts that section 4 lists or adds: the `ToolInvocations` shape and wire, what the step-1 flag means, and the tracker text. The brief is section 9 as amended, plus properties 13 to 17 below. |

**Consumers checked (D10).**
- `step_4n` (`reply_pipeline.py:2410-2415`) reads `attempted` only: same verdict.
- `agent_work_runner.py:384-388` reads `succeeded`: same `tools`.
- `cognitive_agent.py:142-161`: the fold calls `merged_with` for any `ToolInvocations` and skips anything else.
- `cognitive_agent.py:102-122` forwards on `is not None`.
- `cognitive_agent.py:298-312` emits `to_wire()`.
- `cognitive_agent.py:6801-6803` copies the object.
- `cognitive_agent.py:79-99`: the AD-272 cache strips the key.
- `routers/agents.py:3838` is the only reconstruction.
- On the wire: `v` stays 1, a complete record's payload is byte-identical, and `{"v", "attempted", "succeeded", "extra"}` is still malformed (`test_ad1295:481`).
- Federation, the HXI (`ui/src`), `scripts/` and `docs/development` hold no `ToolInvocations` or `tool_invocations` reader.
- The tests naming `ToolInvocations`: only `test_ad1295_tool_success_ledger.py` (24 lines) and `test_ad1358_s2_lookup_claim.py` (9 lines).
- `architecture-baseline.yaml` pins no class touched here, and no method is added.

**What A2 does not change.** The write verdict and `write_ledger.py`; `cognitive_agent.py`, `routers/agents.py` and `agent_work_runner.py`; the step tuples and the group fan-out; any config field (the facade baseline and `config-reference.md` stay as M4 left them); F1 (#1820); S3.

**Milestones.** One Builder delegation of about 30 tool calls: pairs A2-1 to A2-21 and the new file of 16.5. The Builder runs no test. The orchestrator first commits this section and the in-place edits of the contract, as it did for A1. Subject: `Amend the contract with the three findings of review round 1`.
- **M5:** A2-1 to A2-10 and A2-19. Subject: `The lookup check abstains after any retry, on a record that left a call out and on quotes over several lines`.
- **M6:** 16.5 (new file), A2-11 to A2-15, A2-20 and A2-21. Subject: `Tests for the retry, pass order and multi-line quote cases of the lookup check`.
- **M7:** A2-16 to A2-18, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage the two ledger files if they change. Subject: `Trackers for the lookup check after review round 1`.

Every body says `Refs #1750.` No subject or body quotes a test name: several contain a forbidden substring.

**Builder: may and may not.** Section 5, unchanged, applied to the pairs of this section. `tests/test_ad1358_s2_a2_repairs.py` is the one file it creates.

**Gates (added to section 8).**
- Check 8: every SEARCH of A2-1 to A2-21 matches exactly once at its turn on `102e8b33`. Expected: 21 of 21.
- Check 9: on the A2 candidate, `gen_config_reference.py --check` and `check_config_facade.py --check` exit 0 with no regeneration.
- Check 10: 16.5 copied onto `102e8b33` without the source pairs. Expected: a collection error, `ImportError` for `_mask_quoted` from `probos.cognitive.dm.lookup_claim` (A2-20 imports it). The cases are proven by the census instead (A2-M1 to A2-M25; A2-M24 is the first draft of A2-6).
- Focused gate: the command of section 8, with `tests/test_ad1358_s2_a2_repairs.py` (in-place edit E14).
- Preflight: `scripts/run_test_gate.py --preflight-only --label ad-1358-s2` exits 0.
- Then the broad gate once.

**Verified Against Codebase (2026-11-25, tree `102e8b33`).**
```
dm_reply.py:592-622            ToolInvocations attempted/succeeded, from_names, merged_with, to_wire (each once)
dm_reply.py:645-651, :675      from_wire field-set check; value = cls.from_names(raw_attempted, raw_succeeded)
agentic_dispatch.py:2384-2398  dropped warning; P1-8 `if dropped and not attempted: return None`; from_names return
agentic_dispatch.py:2465-2473  "None means the pairs were never read"; tool_invocations default None
agentic_dispatch.py:4449       the one production call of _project_tool_invocations
cognitive_agent.py:142-161     _accumulate_pass_invocations: non-ToolInvocations pass returns early; merged_with
cognitive_agent.py:79-99, 102-122, 298-312, 6801-6803   cache strip, forward, to_wire, act() copy
reply_pipeline.py:188-191      lookup_record_incomplete field comment
reply_pipeline.py:694-734      step 1: try / send (:695); adopted-branch flag (:716-718); except (:729-734)
reply_pipeline.py:2410-2415    step_4n reads attempted; :2458-2459 suffix None / pre-body set on entry
lookup_claim.py:10, :45-46, :61, :75  docstring "adopted no retry"; _QUOTED single-line; the masking call; assess condition
artifact_extractor.py:358-392  BF-866b _fence_spans: same closing rule (same character, at least as long); an unclosed fence runs to the end
dm_sanity_gate.py:113, :531-575  orphaned [CHALLENGE triggers should_retry; strip_markdown edits only around brackets
agent_work_runner.py:384-388   tools = sorted(succeeded)
test_ad1295:474-491            malformed payloads incl. "extra" key; :821-825, :851-858, :959-961 the P2 pins
test_ad1358_s2_lookup_claim.py:118-120, :139   record-decides params; `assert ctx.tool_invocations is None`
```

**Absence Verified (2026-11-25).**

| Claim | Run | Found | Holds |
|---|---|---|---|
| One reconstruction site | `rg "ToolInvocations\.(from_wire\|from_intent_result\|from_names)\|ToolInvocations\(" src` | `agentic_dispatch.py:2398`, `dm_reply.py:611`, `routers/agents.py:3838` | yes |
| No other test names the type | `rg -c ToolInvocations tests` | `test_ad1295` (24), `test_ad1358_s2_lookup_claim` (9) | yes |
| No HXI, docs or scripts reader | `rg -l "tool_invocations\|ToolInvocations" ui/src docs/development scripts` | nothing | yes |
| No test pins the projection's raise path | `rg "projection raised" tests` | nothing | yes |
| No baseline pins the classes | `rg "dm_reply\|lookup_claim\|agentic_dispatch" *baseline*.yaml` | facade field `agentic_dispatch` and key `WorkItemAgenticExecutor` only | yes |

### 16.1 `src/probos/dm_reply.py` (M5)

**A2-1**
SEARCH:
```python
    attempted: tuple[str, ...] = ()
    succeeded: tuple[str, ...] = ()

    @classmethod
    def from_names(
        cls, attempted: Iterable[str], succeeded: Iterable[str],
    ) -> "ToolInvocations":
        """Normalise raw name iterables: de-duplicated, sorted, bounded."""
        return cls(
            attempted=_bounded_tool_names(attempted, "attempted"),
            succeeded=_bounded_tool_names(succeeded, "succeeded"),
        )

    def merged_with(self, other: "ToolInvocations") -> "ToolInvocations":
        """Union, for a turn that ran more than one agentic pass.

        Union rather than last-write-wins: an AD-1164 continuation adds calls,
        and a tool that succeeded on pass 1 still succeeded on this turn.
        """
        return ToolInvocations.from_names(
            tuple(self.attempted) + tuple(other.attempted),
            tuple(self.succeeded) + tuple(other.succeeded),
        )

    def to_wire(self) -> dict[str, Any]:
        """Bounded, JSON-safe payload. Never ``None`` -- see the class docstring."""
        return {
            "v": _WIRE_VERSION,
            "attempted": list(self.attempted),
            "succeeded": list(self.succeeded),
        }
```
REPLACE:
```python
    attempted: tuple[str, ...] = ()
    succeeded: tuple[str, ...] = ()
    #: AD-1358 S2 (#1750): True when the loop made a call this record does not
    #: list, because its id was unverifiable (AD-1295's fail-safe rule drops such
    #: a call from both lists). The lists are as before, so the write verdict is
    #: unchanged; the flag says only that "no call listed" is not "no call made".
    #: ORed by ``merged_with``, so no later pass of the turn can make the record
    #: look complete again. On the wire only when True.
    incomplete: bool = False

    @classmethod
    def from_names(
        cls, attempted: Iterable[str], succeeded: Iterable[str], *, incomplete: bool = False,
    ) -> "ToolInvocations":
        """Normalise raw name iterables: de-duplicated, sorted, bounded."""
        return cls(
            attempted=_bounded_tool_names(attempted, "attempted"),
            succeeded=_bounded_tool_names(succeeded, "succeeded"),
            incomplete=bool(incomplete),
        )

    def merged_with(self, other: "ToolInvocations") -> "ToolInvocations":
        """Union, for a turn that ran more than one agentic pass.

        Union rather than last-write-wins: an AD-1164 continuation adds calls,
        and a tool that succeeded on pass 1 still succeeded on this turn. The
        ``incomplete`` mark is ORed for the same reason: a call one pass could
        not list was still made on this turn (AD-1358 S2).
        """
        return ToolInvocations.from_names(
            tuple(self.attempted) + tuple(other.attempted),
            tuple(self.succeeded) + tuple(other.succeeded),
            incomplete=self.incomplete or other.incomplete,
        )

    def to_wire(self) -> dict[str, Any]:
        """Bounded, JSON-safe payload. Never ``None`` -- see the class docstring.

        ``incomplete`` is present only when True, so a complete record keeps the
        AD-1295 payload byte for byte (AD-1358 S2).
        """
        payload: dict[str, Any] = {
            "v": _WIRE_VERSION,
            "attempted": list(self.attempted),
            "succeeded": list(self.succeeded),
        }
        if self.incomplete:
            payload["incomplete"] = True
        return payload
```

**A2-2**
SEARCH:
```python
            if set(payload) != {"v", "attempted", "succeeded"}:
                logger.warning(
                    "AD-1295: tool-invocation metadata field set %r is not the "
                    "wire shape; treating as malformed rather than reconciling",
```
REPLACE:
```python
            # AD-1358 S2 (#1750): ``incomplete`` is on the wire only when it is
            # true; any other value of the key is malformed, like any extra key.
            incomplete = "incomplete" in payload
            if set(payload) - {"incomplete"} != {"v", "attempted", "succeeded"} or (
                incomplete and payload["incomplete"] is not True
            ):
                logger.warning(
                    "AD-1295: tool-invocation metadata field set %r is not the "
                    "wire shape; treating as malformed rather than reconciling",
```

**A2-3**
SEARCH:
```python
            value = cls.from_names(raw_attempted, raw_succeeded)
            if not set(value.succeeded) <= set(value.attempted):
                logger.warning(
```
REPLACE:
```python
            value = cls.from_names(raw_attempted, raw_succeeded, incomplete=incomplete)
            if not set(value.succeeded) <= set(value.attempted):
                logger.warning(
```

### 16.2 `src/probos/cognitive/agentic_dispatch.py` (M5)

**A2-4**
SEARCH:
```python
        if dropped and not attempted:
            # AD-1358 S2 (#1750): every call was unverifiable, so an empty record would say "this turn
            # called no tool", which it did. None says the record cannot be read (AD-1269). The write
            # verdict is the same either way: ``step_4n`` consults no channel for None or for an
            # empty ``attempted``.
            return None
        return ToolInvocations.from_names(attempted, succeeded)
```
REPLACE:
```python
        # AD-1358 S2 (#1750): a record that left calls out says so. Without the mark, a turn whose every
        # call was unverifiable would read as "called no tool", which it did not. The mark rides the
        # record through the pass union (``merged_with``) and the wire, so no later pass can make the
        # record look complete. The lists, and so the write verdict, are unchanged: ``step_4n`` reads
        # ``attempted`` only.
        return ToolInvocations.from_names(attempted, succeeded, incomplete=bool(dropped))
```

### 16.3 `src/probos/cognitive/dm/lookup_claim.py` (M5)

**A2-5**
SEARCH:
```python
``assess_lookup_claim`` abstains (returns None) unless all of these hold: the record is a ``ToolInvocations`` (None
means the loop did not run or its record could not be read, AD-1269); it lists no call; the pipeline saw no
in-reply read and adopted no retry (``record_incomplete`` is exactly False); and ``find_lookup_claim`` finds a claim.
```
REPLACE:
```python
``assess_lookup_claim`` abstains (returns None) unless all of these hold: the record is a ``ToolInvocations`` (None
means the loop did not run or its record could not be read, AD-1269); it lists no call and its ``incomplete`` mark
is exactly False (no call of any pass of the turn was left out for an unverifiable id); the pipeline saw no in-reply
read and dispatched no retry (``record_incomplete`` is exactly False); and ``find_lookup_claim`` finds a claim.
```

**A2-6**
SEARCH:
```python
#: Quoted text is not the agent's claim: double and curly quotes, backticks, block-quote lines.
_QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`|^[ \t]*>.*$', re.MULTILINE)
```
REPLACE:
```python
#: Quoted text is not the agent's claim (``_mask_quoted``): a fenced block, only with its closing line (the first
#: later line made only of the same fence character, at least as many, and spaces); paired double quotes, paired
#: curly quotes and backtick spans, each of which may run over line breaks but not over a blank line, so a stray
#: quote reaches no further than its paragraph; and block-quote lines. An unclosed fence or an unpaired quote masks
#: nothing: a missed mask appends a sentence that is true of the record, a wide one hides it.
_FENCE_RUN = re.compile(r"[ \t]*(`{3,}|~{3,})")
_FENCE_ONLY = re.compile(r"[ \t]*(?:`{3,}|~{3,})[ \t]*")
_SPAN_START = re.compile(r'["`\u201c]|^[ \t]*>', re.MULTILINE)
_SPAN_END = {'"': '"', "`": "`", "\u201c": "\u201d"}
#: A line break that starts a blank line: no quote or backtick span crosses one.
_PARAGRAPH_BREAK = re.compile(r"\n(?=[ \t]*\n)")


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """The character spans of the fenced blocks that have a closing line, in order.

    Linear in the length of ``text``: a backward pass records, for every line, the longest closing line of each
    fence character after it, so an opener that nothing ends costs one lookup instead of a scan to the end.
    """
    lines = text.split("\n")
    count = len(lines)
    starts: list[int] = []
    runs: list[str] = []
    ending: list[bool] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1
        match = _FENCE_RUN.match(line)
        run = match.group(1) if match else ""
        runs.append(run)
        ending.append(bool(run) and _FENCE_ONLY.fullmatch(line) is not None)
    longest_after = {"`": [0] * count, "~": [0] * count}
    longest = {"`": 0, "~": 0}
    for index in range(count - 1, -1, -1):
        longest_after["`"][index] = longest["`"]
        longest_after["~"][index] = longest["~"]
        if ending[index]:
            char = runs[index][0]
            longest[char] = max(longest[char], len(runs[index]))
    spans: list[tuple[int, int]] = []
    index = 0
    while index < count:
        run = runs[index]
        if not run or longest_after[run[0]][index] < len(run):
            index += 1
            continue
        last = index + 1
        while not (ending[last] and runs[last][0] == run[0] and len(runs[last]) >= len(run)):
            last += 1
        spans.append((starts[index], starts[last] + len(lines[last])))
        index = last + 1
    return spans


def _mask_quoted(text: str) -> str:
    """``text`` with every quoted span blanked to spaces. Line breaks are kept, so its length and lines are kept.

    Linear in the length of ``text`` for every input: ``pos`` only moves forward and a found span is skipped
    whole; a failed search for a straight quote or a backtick proves no opener of its kind remains before the
    paragraph break it stopped at; a failed search for a closing curly quote marks the rest of the paragraph, so
    no later curly opener there searches again.
    """
    fences = _fenced_spans(text)
    spans = list(fences)
    breaks = [match.start() for match in _PARAGRAPH_BREAK.finditer(text)]
    next_fence = 0
    next_break = 0
    curly_dead_until = -1
    pos = 0
    while (match := _SPAN_START.search(text, pos)) is not None:
        start = match.start()
        while next_fence < len(fences) and fences[next_fence][1] <= start:
            next_fence += 1
        if next_fence < len(fences) and fences[next_fence][0] <= start:
            pos = fences[next_fence][1]
            continue
        opener = match.group(0)
        if opener.endswith(">"):
            line_end = text.find("\n", start)
            line_end = len(text) if line_end < 0 else line_end
            spans.append((start, line_end))
            pos = line_end
            continue
        while next_break < len(breaks) and breaks[next_break] < start:
            next_break += 1
        limit = breaks[next_break] if next_break < len(breaks) else len(text)
        if opener == "\u201c" and start < curly_dead_until:
            pos = start + 1
            continue
        stop = text.find(_SPAN_END[opener], start + 1, limit)
        if stop < 0:
            if opener == "\u201c":
                curly_dead_until = limit
            pos = start + 1
            continue
        spans.append((start, stop + 1))
        pos = stop + 1
    if not spans:
        return text
    chars = list(text)
    for begin, end in spans:
        for index in range(begin, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)
```

**A2-7**
SEARCH:
```python
    if type(invocations) is not ToolInvocations or invocations.attempted or invocations.succeeded:
        return None
    return find_lookup_claim(text)
```
REPLACE:
```python
    if type(invocations) is not ToolInvocations or invocations.attempted or invocations.succeeded:
        return None
    if invocations.incomplete is not False:
        # A call this record could not list (an unverifiable id) may have been a lookup.
        return None
    return find_lookup_claim(text)
```

### 16.4 `src/probos/cognitive/dm/reply_pipeline.py` (M5)

**A2-8**
SEARCH:
```python
    # AD-1358 S2 (#1750): True when this reply's reads are not all in ``tool_invocations``: an adopted
    # retry (step 1 keeps the first attempt's record), an ``[ACTION:]`` marker (step 4e) or a
    # ``[MESH ...]`` read (step 4h). The lookup-claim check in step 4m abstains when it is set.
```
REPLACE:
```python
    # AD-1358 S2 (#1750): True when this reply's reads are not all in ``tool_invocations``: a dispatched
    # retry (step 1 keeps the first attempt's record, whatever the retry ran or returned), an ``[ACTION:]``
    # marker (step 4e) or a ``[MESH ...]`` read (step 4h). The lookup-claim check in step 4m abstains when
    # it is set.
```

**A2-9**
SEARCH:
```python
                try:
                    retry_resp = await self.ctx.runtime.intent_bus.send(retry_intent)
                    retry_text = ""
```
REPLACE:
```python
                # AD-1358 S2 (#1750): set before the send. A retry can run tools whatever it then returns
                # (text, no text, None, a raise after a timeout), and ``ctx.tool_invocations`` stays the
                # first attempt's record in every case, so the lookup-claim check abstains for this reply.
                self.ctx.lookup_record_incomplete = True
                try:
                    retry_resp = await self.ctx.runtime.intent_bus.send(retry_intent)
                    retry_text = ""
```

**A2-10**
SEARCH:
```python
                        # AD-1358 S2 (#1750): ``ctx.tool_invocations`` is still the first
                        # attempt's record, so the lookup-claim check abstains for this reply.
                        self.ctx.lookup_record_incomplete = True
                        # AD-1360 (#1828): the reply now comes from the retry's own cycle, so the steps after this one
```
REPLACE:
```python
                        # AD-1360 (#1828): the reply now comes from the retry's own cycle, so the steps after this one
```

### 16.5 `tests/test_ad1358_s2_a2_repairs.py` (M6, new file)

```python
"""AD-1358 S2 (#1750), amendment A2: the three findings of review round 1.

Contract: prompts/ad-1358-s2-lookup-claim-trace.md, section 16 (R1-1, R1-2, R1-3). Real objects: the real
projection, the real pass fold, the real metadata builder, a real IntentResult, the route's reconstruction,
the real DmSanityGate and the real pipeline. Only the intent bus is a stand-in.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome, _project_tool_invocations
from probos.cognitive.cognitive_agent import (
    _accumulate_pass_invocations,
    _attach_run_provenance,
    _build_result_metadata,
)
from probos.cognitive.dm.lookup_claim import LOOKUP_DISCLOSURE, find_lookup_claim
from probos.cognitive.dm.reply_pipeline import DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.dm_reply import ToolInvocations
from probos.types import IntentResult
from tests.test_ad1295_tool_success_ledger import (
    DISCLOSURE_FRAGMENT,
    FINDING,
    _CapturingEpisodicMemory,
    _OverridingAgent,
    _agentic_result,
    _agentic_result_with_ids,
    _make_ctx,
    _runtime,
)
from tests.test_ad1358_s2_lookup_claim import _ctx_for_turn

_LOGGER = "probos.cognitive.dm.reply_pipeline"
_CLAIM = "I searched the records and found nothing for that."
_FENCE = "`" * 3


# --- R1-1: a dispatched retry, whatever it returns ------------------------------------------------------

#: A claim and an orphaned ``[CHALLENGE`` tag: the real gate keeps the claim and asks for one retry.
_REJECTED = _CLAIM + " [CHALLENGE"
_NO_RESPONSE = object()


class _RetryBus:
    """The one stand-in: answers the retry with ``response``, or raises as a timed-out dispatch does."""

    def __init__(self, response, *, raises: bool = False) -> None:
        self.response = response
        self.raises = raises
        self.sent: list = []

    async def send(self, intent):
        self.sent.append(intent)
        if self.raises:
            raise TimeoutError("the retry timed out; its tools may have run")
        return self.response


def _ctx_with_gate(reply: str, bus: _RetryBus):
    runtime = _runtime(episodic=_CapturingEpisodicMemory())
    runtime.intent_bus = bus
    ctx = _ctx_for_turn(_agentic_result([]), reply, runtime=runtime)
    ctx.sanity_gate = DmSanityGate()
    return ctx


@pytest.mark.parametrize(("answer", "raises"), [
    pytest.param("The record I found shows it as a draw.", False, id="adopted"),
    pytest.param("", False, id="empty-text"),
    pytest.param(None, False, id="none-result"),
    pytest.param(_NO_RESPONSE, False, id="no-response"),
    pytest.param(_NO_RESPONSE, True, id="raised"),
])
def test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns(answer, raises) -> None:
    response = None if answer is _NO_RESPONSE else IntentResult(
        intent_id="i-2", agent_id="a1", success=True, result=answer,
    )
    bus = _RetryBus(response, raises=raises)
    ctx = _ctx_with_gate(_REJECTED, bus)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert len(bus.sent) == 1, "premise: the gate dispatched one retry"
    assert find_lookup_claim(ctx.pre_write_disclosure_body) is not None, "premise: the reply claims a lookup"
    assert ctx.lookup_record_incomplete is True
    assert ctx.write_disclosure_suffix is None
    assert LOOKUP_DISCLOSURE not in ctx.response_text


def test_a_reply_the_gate_accepts_dispatches_no_retry_and_is_checked() -> None:
    bus = _RetryBus(None)
    ctx = _ctx_with_gate(_CLAIM, bus)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert bus.sent == [], "premise: the gate accepted the reply"
    assert ctx.lookup_record_incomplete is False
    assert ctx.write_disclosure_suffix == LOOKUP_DISCLOSURE
    assert ctx.response_text == ctx.pre_write_disclosure_body + LOOKUP_DISCLOSURE


# --- R1-2: an unverifiable call, in any pass of the turn --------------------------------------------------

def _pass(kind: str):
    """One agentic pass of a turn, as the loop records it."""
    if kind == "empty":
        return _agentic_result([])
    if kind == "unverifiable":
        return _agentic_result_with_ids([("oracle_query", True, None)])
    if kind == "lookup":
        return _agentic_result([("oracle_query", True)])
    assert kind == "failed-write"
    return _agentic_result([(FINDING, False)])


def _ctx_for_passes(kinds: list[str], reply: str):
    """The real fold over several passes of one turn, the real metadata builder, the route's reconstruction."""
    observation: dict = {"intent": "direct_message"}
    for kind in kinds:
        outcome = WorkItemAgenticOutcome(
            final_text="done", tool_invocations=_project_tool_invocations(_pass(kind)),
        )
        _accumulate_pass_invocations(observation, outcome)
    decision = {"action": "execute", "llm_output": reply}
    _attach_run_provenance(decision, observation)
    report = asyncio.run(_OverridingAgent().act(decision))
    result = IntentResult(
        intent_id="i-1", agent_id="a1", success=True, result=reply,
        metadata=_build_result_metadata(report, decision, observation),
    )
    return _make_ctx(
        runtime=_runtime(episodic=_CapturingEpisodicMemory()),
        response_text=reply,
        tool_invocations=ToolInvocations.from_intent_result(result),
    )


@pytest.mark.parametrize(("kinds", "fires"), [
    pytest.param(["unverifiable"], False, id="unverifiable-only"),
    pytest.param(["unverifiable", "empty"], False, id="unverifiable-first"),
    pytest.param(["empty", "unverifiable"], False, id="unverifiable-last"),
    pytest.param(["empty", "unverifiable", "empty"], False, id="unverifiable-between"),
    pytest.param(["unverifiable", "failed-write", "empty"], False, id="with-known-call"),
    pytest.param(["lookup", "empty"], False, id="control-correlatable-first"),
    pytest.param(["empty", "empty"], True, id="control-two-empty-passes"),
])
def test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order(kinds, fires) -> None:
    ctx = _ctx_for_passes(kinds, "I searched the records: two games.")
    assert type(ctx.tool_invocations) is ToolInvocations, "premise: the route rebuilt a record"
    assert ctx.tool_invocations.incomplete is ("unverifiable" in kinds)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert (LOOKUP_DISCLOSURE in ctx.response_text) is fires


def test_a_known_write_and_the_incomplete_mark_both_survive_the_fold() -> None:
    ctx = _ctx_for_passes(["unverifiable", "failed-write", "empty"], "I searched the records first.")
    assert ctx.tool_invocations == ToolInvocations.from_names([FINDING], [], incomplete=True)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert DISCLOSURE_FRAGMENT in ctx.response_text, "the write guard still reports the failed save"
    assert LOOKUP_DISCLOSURE not in ctx.response_text


@pytest.mark.parametrize(("triples", "attempted", "incomplete"), [
    pytest.param([("read_file", True, None), (FINDING, False, "c-1")], (FINDING,), True, id="sibling-kept"),
    pytest.param([("oracle_query", True, None)], (), True, id="all-unverifiable"),
    pytest.param([(FINDING, True, "same"), ("read_file", False, "same")], (), True, id="duplicate-ids"),
    pytest.param([("oracle_query", True, "c-1")], ("oracle_query",), False, id="well-formed"),
    pytest.param([], (), False, id="no-calls"),
])
def test_the_projection_marks_a_record_that_left_a_call_out(triples, attempted, incomplete) -> None:
    inv = _project_tool_invocations(_agentic_result_with_ids(triples))
    assert type(inv) is ToolInvocations
    assert inv.attempted == attempted
    assert inv.incomplete is incomplete


def test_merged_with_keeps_the_incomplete_mark_in_either_order() -> None:
    marked = ToolInvocations(incomplete=True)
    assert ToolInvocations().merged_with(marked).incomplete is True
    assert marked.merged_with(ToolInvocations()).incomplete is True
    assert ToolInvocations().merged_with(ToolInvocations()) == ToolInvocations()
    known = ToolInvocations.from_names([FINDING], [FINDING])
    assert marked.merged_with(known) == ToolInvocations.from_names([FINDING], [FINDING], incomplete=True)


def test_a_complete_record_keeps_the_ad1295_wire_shape() -> None:
    assert ToolInvocations().to_wire() == {"v": 1, "attempted": [], "succeeded": []}
    assert set(ToolInvocations.from_names([FINDING], []).to_wire()) == {"v", "attempted", "succeeded"}


def test_an_incomplete_record_round_trips_on_the_wire() -> None:
    value = ToolInvocations.from_names([FINDING], [], incomplete=True)
    payload = value.to_wire()
    assert payload == {"v": 1, "attempted": [FINDING], "succeeded": [], "incomplete": True}
    assert ToolInvocations.from_wire(payload) == value
    assert ToolInvocations.from_wire(ToolInvocations(incomplete=True).to_wire()) == ToolInvocations(incomplete=True)


@pytest.mark.parametrize("flag", [
    pytest.param(False, id="false"),
    pytest.param(1, id="one"),
    pytest.param("true", id="string"),
    pytest.param(None, id="null"),
])
def test_an_incomplete_key_that_is_not_true_reads_as_no_record(flag) -> None:
    assert ToolInvocations.from_wire({"v": 1, "attempted": [], "succeeded": [], "incomplete": flag}) is None


# --- R1-3: quoted wording over several lines --------------------------------------------------------------

_FENCED = (
    "Here is the template:\n" + _FENCE + "\nGood evening.\n\n"
    "I searched the records and found two games.\n" + _FENCE + "\nFill it in."
)
_QUOTED_OVER_LINES = (
    'Say it like this: "Good evening, Captain.\nI searched the records and found two games." That is the form.'
)
_UNQUOTED = "Here is the template:\nGood evening.\n\nI searched the records and found two games.\nFill it in."


@pytest.mark.parametrize("text", [
    pytest.param(_FENCED, id="fence-with-blank-line"),
    pytest.param("~~~\nI searched the records and found two games.\n~~~", id="tilde-fence"),
    pytest.param(_FENCE + "text\nThe record I found shows it as a draw.\n" + _FENCE, id="fence-info-string"),
    pytest.param(_QUOTED_OVER_LINES, id="multi-line-double-quote"),
    pytest.param("\u201cGood evening.\nI searched the records.\u201d That was the line.", id="multi-line-curly"),
    pytest.param("Use `the phrase\nI searched the records` as the test.", id="multi-line-backtick"),
])
def test_wording_quoted_over_several_lines_is_not_found(text) -> None:
    assert find_lookup_claim(text) is None


@pytest.mark.parametrize("text", [
    pytest.param(_FENCE + "\nexample\n" + _FENCE + "\nI searched the records and found two games.",
                 id="after-a-closed-fence"),
    pytest.param(_FENCE + "\nI searched the records and found two games.", id="unclosed-fence"),
    pytest.param('The board is 6" wide.\n\nI searched the records and found the "draw" entry.',
                 id="stray-quote-stops-at-blank-line"),
    pytest.param('He said "hi.\nI searched the records and found two games.', id="unpaired-quote"),
])
def test_an_unquoted_claim_beside_a_fence_or_quote_is_found(text) -> None:
    found = find_lookup_claim(text)
    assert found is not None and "i searched" in found.lower()


@pytest.mark.parametrize(("reply", "fires"), [
    pytest.param(_FENCED, False, id="fenced-block"),
    pytest.param(_QUOTED_OVER_LINES, False, id="multi-line-quote"),
    pytest.param(_UNQUOTED, True, id="unquoted-control"),
])
def test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged(reply, fires, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    ctx = _ctx_for_turn(_agentic_result([]), reply)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert (ctx.write_disclosure_suffix == LOOKUP_DISCLOSURE) is fires
    assert ctx.response_text == ctx.pre_write_disclosure_body + (LOOKUP_DISCLOSURE if fires else "")
    assert any("lookup-claim check" in r.getMessage() for r in caplog.records) is fires
```

### 16.6 `tests/test_ad1358_s2_lookup_claim.py` (M6)

**A2-11**
SEARCH:
```python
    pytest.param(ToolInvocations(), True, False, id="incomplete"),
    pytest.param(ToolInvocations(), 1, False, id="incomplete-not-a-bool"),
    pytest.param(ToolInvocations(), False, True, id="empty-record"),
```
REPLACE:
```python
    pytest.param(ToolInvocations(), True, False, id="incomplete"),
    pytest.param(ToolInvocations(), 1, False, id="incomplete-not-a-bool"),
    pytest.param(ToolInvocations(incomplete=True), False, False, id="record-incomplete"),
    pytest.param(ToolInvocations(incomplete=1), False, False, id="record-incomplete-not-a-bool"),
    pytest.param(ToolInvocations(), False, True, id="empty-record"),
```

**A2-12**
SEARCH:
```python
    ctx = _ctx_for_turn(_agentic_result_with_ids([("oracle_query", True, None)]), reply)
    assert ctx.tool_invocations is None
    asyncio.run(DmReplyPipeline(ctx).run())
```
REPLACE:
```python
    ctx = _ctx_for_turn(_agentic_result_with_ids([("oracle_query", True, None)]), reply)
    # Amendment A2 (R1-2): not None; the record lists no call and says it left one out.
    assert ctx.tool_invocations == ToolInvocations(incomplete=True)
    asyncio.run(DmReplyPipeline(ctx).run())
```

### 16.7 `tests/test_ad1295_tool_success_ledger.py` (M6)

**A2-13**
SEARCH:
```python
    # AD-1358 S2 (#1750): was an empty record. With every call unverifiable the record is None, so
    # an empty one always means "called no tool"; the write guard abstains for both (step_4n).
    assert inv is None
```
REPLACE:
```python
    # AD-1358 S2 (#1750), amendment A2: the lists are empty, as before AD-1358, and the record says
    # it left a call out, so an empty record that is not ``incomplete`` always means "called no
    # tool". The write guard reads ``attempted`` only, so it abstains here as before (step_4n).
    assert inv is not None
    assert inv.attempted == ()
    assert inv.succeeded == ()
    assert inv.incomplete is True
```

**A2-14**
SEARCH:
```python
    # AD-1358 S2 (#1750): was an empty record; every call is unverifiable, so the record is None.
    assert inv is None
```
REPLACE:
```python
    # AD-1358 S2 (#1750), amendment A2: every call is unverifiable: empty lists, as before AD-1358,
    # and a record that says it left them out.
    assert inv is not None
    assert inv.attempted == ()
    assert inv.succeeded == ()
    assert inv.incomplete is True
```

**A2-15**
SEARCH:
```python
    # AD-1358 S2 (#1750): was an empty record; every call is unverifiable, so there is no record.
    # The assertions below (no write sentence, an untouched ledger) are unchanged.
    assert ctx.tool_invocations is None
```
REPLACE:
```python
    # AD-1358 S2 (#1750), amendment A2: every call is unverifiable: empty lists, as before AD-1358,
    # and a record marked incomplete. The assertions below (no write sentence, an untouched ledger)
    # are unchanged.
    assert ctx.tool_invocations is not None
    assert ctx.tool_invocations.attempted == ()
    assert ctx.tool_invocations.succeeded == ()
    assert ctx.tool_invocations.incomplete is True
```

### 16.8 `PROGRESS.md` (M7)

**A2-16**
SEARCH:
```markdown
**AD-1358 S2 (2026-11-25), #1750 -- a 1:1 reply that says it searched or looked something up, on a turn whose tool record holds no call, carries one appended sentence.** New `cognitive/dm/lookup_claim.py`: `find_lookup_claim` reads the reply's own wording (outside double quotes, backticks and block quotes) for a past-tense search or record-lookup claim that is not negated, conditional, a question or about the agent's memory; `assess_lookup_claim` returns it only when the turn's `ToolInvocations` is present and lists no call and `DmReplyContext.lookup_record_incomplete` is False (set by steps 1, 4e and 4h for an adopted retry, an `[ACTION:]` marker and a `[MESH]` read). `step_4m_write_claim_guard` appends `LOOKUP_DISCLOSURE` after any write sentence, under `write_claim_guard.enabled`, and logs the claim at WARNING. `_project_tool_invocations` returns None when every call's id is unverifiable. Measured by `tests/test_ad1358_s2_lookup_claim.py` (13 functions, 45 cases): the two live sentences of 2026-11-04, on a turn with an empty record, through the real producer chain and `DmReplyPipeline.run()`, end with the sentence in the reply, the response and the episode, and the log names the claim; a turn whose lookup ran, a turn whose only call had an unverifiable id, the switch off, a `[MESH]` read, an `[ACTION:]` marker, an adopted retry and the Captain's own words leave the reply unchanged; 16 wordings are not claims; the write and lookup sentences compose. Three pins in `tests/test_ad1295_tool_success_ledger.py` now expect no record for an all-unverifiable turn. Mutation census: 19 of 19 killed, each by a test the contract names (rows LC-1 to LC-19), run once on the candidate overlay of `8704d194`. Not measured: a live DM turn. Claims about shared history and the issue's DM acceptance are S3. Contract `prompts/ad-1358-s2-lookup-claim-trace.md`.
```
REPLACE:
```markdown
**AD-1358 S2 (2026-11-25), #1750 -- a 1:1 reply that says it searched or looked something up, on a turn whose tool record holds no call, carries one appended sentence.** New `cognitive/dm/lookup_claim.py`: `find_lookup_claim` reads the reply's own wording (outside fenced blocks, paired double and curly quotes and backtick spans, which may run over line breaks but not over a blank line, and block quotes) for a past-tense search or record-lookup claim that is not negated, conditional, a question or about the agent's memory; `assess_lookup_claim` returns it only when the turn's `ToolInvocations` is present, lists no call and is not marked `incomplete`, and `DmReplyContext.lookup_record_incomplete` is False (set by step 1 whenever it dispatches a retry, whatever the retry returns, and by steps 4e and 4h for an `[ACTION:]` marker and a `[MESH]` read). `step_4m_write_claim_guard` appends `LOOKUP_DISCLOSURE` after any write sentence, under `write_claim_guard.enabled`, and logs the claim at WARNING. `ToolInvocations` gains an `incomplete` mark, on the wire only when true and ORed across the passes of a turn, which `_project_tool_invocations` sets when it leaves out a call whose id is unverifiable; the lists, and so the write verdict, are unchanged. Measured by `tests/test_ad1358_s2_lookup_claim.py` (13 functions, 47 cases): the two live sentences of 2026-11-04, on a turn with an empty record, through the real producer chain and `DmReplyPipeline.run()`, end with the sentence in the reply, the response and the episode, and the log names the claim; a turn whose lookup ran, a turn whose only call had an unverifiable id, the switch off, a `[MESH]` read, an `[ACTION:]` marker, an adopted retry and the Captain's own words leave the reply unchanged; 16 wordings are not claims; the write and lookup sentences compose. And by `tests/test_ad1358_s2_a2_repairs.py` (15 functions, 46 cases), the repairs of review round 1: a retry that returns text, empty text, None or nothing, or raises, leaves the reply without the sentence, and a reply the gate accepts is still checked (`test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns`, `test_a_reply_the_gate_accepts_dispatches_no_retry_and_is_checked`); an unverifiable call keeps the turn's record incomplete whether its pass comes first, last or between, and a known write survives the fold (`test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order`, `test_a_known_write_and_the_incomplete_mark_both_survive_the_fold`); a complete record keeps the AD-1295 wire shape and an incomplete one round-trips (`test_a_complete_record_keeps_the_ad1295_wire_shape`, `test_an_incomplete_record_round_trips_on_the_wire`); a claim inside a fenced block or a quote that runs over lines is not found and leaves the reply unchanged, while the same claim unquoted, after an unclosed fence or past a stray quote's paragraph is found (`test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged`, `test_an_unquoted_claim_beside_a_fence_or_quote_is_found`); a fence ends only at a later line of its own character at least as long, the masking keeps the reply's length and line breaks, and it takes linear time on 16,000 unclosed fence lines or unpaired curly quotes (`test_a_fence_ends_only_on_its_own_kind_and_length`, `test_masking_keeps_length_and_line_breaks`, `test_masking_takes_linear_time_on_unclosed_openers`). Three pins in `tests/test_ad1295_tool_success_ledger.py` now expect empty lists and the `incomplete` mark for an all-unverifiable turn. Mutation census: 19 of 19 killed (rows LC-1 to LC-19, run once on the candidate overlay of `8704d194`) and 25 of 25 killed (rows A2-M1 to A2-M25, run once on the A2 overlay of `102e8b33`), each by a test the contract names. Not measured: a live DM turn. Claims about shared history and the issue's DM acceptance are S3. Contract `prompts/ad-1358-s2-lookup-claim-trace.md`.
```

### 16.9 `DECISIONS.md` (M7)

**A2-17**
SEARCH:
```markdown
- *Scope.* `cognitive/dm/lookup_claim.py` (new), `cognitive/dm/reply_pipeline.py` (`step_4m`, the `lookup_record_incomplete` field, steps 1, 4e and 4h), `cognitive/agentic_dispatch.py` (`_project_tool_invocations`), the `write_claim_guard.enabled` description; tests. Contract `prompts/ad-1358-s2-lookup-claim-trace.md`.
```
REPLACE:
```markdown
- *Scope.* `cognitive/dm/lookup_claim.py` (new), `cognitive/dm/reply_pipeline.py` (`step_4m`, the `lookup_record_incomplete` field, steps 1, 4e and 4h), `cognitive/agentic_dispatch.py` (`_project_tool_invocations`), `dm_reply.py` (`ToolInvocations.incomplete`, amendment A2), the `write_claim_guard.enabled` description; tests. Contract `prompts/ad-1358-s2-lookup-claim-trace.md`.
```

**A2-18**
SEARCH:
```markdown
- *LC5 (unverifiable ids).* A record whose every call was unverifiable is None, not empty; the write verdict is unchanged.
- *Not changed.* `write_ledger.py`, `ToolInvocations` and its wire shape, the step tuples, the group fan-out, config fields.
```
REPLACE:
```markdown
- *LC5 (unverifiable ids).* A record that left out a call whose id was unverifiable is marked `incomplete` (on the wire only when true, ORed across the passes of a turn), and the check abstains on it; the lists, and so the write verdict, are unchanged (`test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order`, `test_a_known_write_and_the_incomplete_mark_both_survive_the_fold`). Rejected in review round 1: a None record for such a pass, which the pass fold skips, so a later empty pass restored "called no tool"; a second metadata key beside the record (two facts that must travel together); a None that absorbs the union (loses known write evidence).
- *LC6 (retry).* Step 1 marks the reply's record incomplete when it dispatches a retry, before the send, whatever the retry returns: a retry can run tools and `ctx.tool_invocations` stays the first attempt's record (`test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns`, `test_a_reply_the_gate_accepts_dispatches_no_retry_and_is_checked`).
- *LC7 (quoted wording).* A fenced block is masked only with its closing fence; quote and backtick spans may run over line breaks but not over a blank line, so a stray quote hides at most the rest of its paragraph; a fence ends at the first later line made only of its own character, at least as long; the masking takes time linear in the reply's length, and one regex for all of it was rejected as quadratic on unclosed fence lines (`test_a_fence_ends_only_on_its_own_kind_and_length`, `test_masking_keeps_length_and_line_breaks`, `test_masking_takes_linear_time_on_unclosed_openers`, `test_wording_quoted_over_several_lines_is_not_found`, `test_an_unquoted_claim_beside_a_fence_or_quote_is_found`, `test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged`).
- *Not changed.* `write_ledger.py`, the wire shape of a complete `ToolInvocations` record (the `incomplete` key appears only when true), the step tuples, the group fan-out, config fields.
```

### 16.10 Mutation census (A2): run once on the A2 overlay (`102e8b33` plus A2-1 to A2-15 and A2-19 to A2-21), the campaign of record

"A2 file" is `tests/test_ad1358_s2_a2_repairs.py`; "S2 file" is `tests/test_ad1358_s2_lookup_claim.py`; "ad1295" is `tests/test_ad1295_tool_success_ledger.py`.

| Row | Mutant | Killer |
|---|---|---|
| A2-M1 | Step 1: flag only inside the adopted branch (the draft's place) | A2 file `test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns[empty-text, none-result, no-response, raised]` |
| A2-M2 | Step 1: flag set inside `try` after the `send` line | `...whatever_it_returns[raised]` |
| A2-M3 | Step 1: flag set before `if sanity_result.should_retry:` | `test_a_reply_the_gate_accepts_dispatches_no_retry_and_is_checked` |
| A2-M4 | Projection: `incomplete=bool(dropped and not attempted)` | `test_the_projection_marks_a_record_that_left_a_call_out[sibling-kept]` |
| A2-M5 | Projection: `incomplete=False` | `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-only, -first, -last, -between, with-known-call]`; `test_the_projection_marks...[sibling-kept, all-unverifiable, duplicate-ids]`; S2 file `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed`; ad1295 `test_unverifiable_call_is_omitted_from_attempted`, `test_duplicate_call_ids_are_uncorrelatable`, `test_unverifiable_id_abstains_through_the_whole_pipeline` |
| A2-M6 | Projection: `incomplete=True` | `test_the_projection_marks...[well-formed, no-calls]`; `...every_pass_order[control-two-empty-passes, control-correlatable-first]`; S2 file `test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed` |
| A2-M7 | `merged_with`: `incomplete=other.incomplete` | `test_merged_with_keeps_the_incomplete_mark_in_either_order`; `...every_pass_order[unverifiable-first]` |
| A2-M8 | `merged_with`: `incomplete=self.incomplete` | `test_merged_with_keeps...`; `...every_pass_order[unverifiable-last, unverifiable-between]` |
| A2-M9 | `to_wire`: never emits `incomplete` | `test_an_incomplete_record_round_trips_on_the_wire`; `...every_pass_order[unverifiable-*]` |
| A2-M10 | `to_wire`: always emits `"incomplete": self.incomplete` | `test_a_complete_record_keeps_the_ad1295_wire_shape` |
| A2-M11 | `from_wire`: drop `and payload["incomplete"] is not True` | `test_an_incomplete_key_that_is_not_true_reads_as_no_record[false, one, string, null]` |
| A2-M12 | `from_wire`: `cls.from_names(raw_attempted, raw_succeeded)` (mark dropped) | `test_an_incomplete_record_round_trips_on_the_wire`; `...every_pass_order[unverifiable-*]` |
| A2-M13 | `assess`: delete the `incomplete` check | S2 file `test_the_record_decides[record-incomplete]`; `...every_pass_order[unverifiable-only, -first, -last, -between]`; S2 file `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed` |
| A2-M14 | `assess`: `invocations.incomplete is True` | S2 file `test_the_record_decides[record-incomplete-not-a-bool]` |
| A2-M15 | `_mask_quoted`: `fences = []` (no fence pass) | `test_wording_quoted_over_several_lines_is_not_found[fence-with-blank-line, tilde-fence]`; `test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged[fenced-block]`; `test_masking_keeps_length_and_line_breaks` |
| A2-M16 | A double quote is searched only to the end of its line (`limit = text.find("\n", start)` when `opener == '"'`) | `...is_not_found[multi-line-double-quote]`; `...leaves_the_reply_unchanged[multi-line-quote]`; `test_masking_keeps_length_and_line_breaks` |
| A2-M17 | Paragraph breaks ignored (`limit = len(text)`) | `test_an_unquoted_claim_beside_a_fence_or_quote_is_found[stray-quote-stops-at-blank-line]` |
| A2-M18 | An opener that nothing ends masks to the end of the text (`spans.append((starts[index], len(text)))` and `break`, in place of `index += 1` when `longest_after` is short) | `...is_found[unclosed-fence]`; `test_a_fence_ends_only_on_its_own_kind_and_length[block-after-stray-opener]`; `test_masking_takes_linear_time_on_unclosed_openers[unopened-backtick-fences, unopened-tilde-fences]` |
| A2-M19 | An opening curly quote is searched only to the end of its line | `...is_not_found[multi-line-curly]` |
| A2-M20 | A backtick is searched only to the end of its line | `...is_not_found[multi-line-backtick]` |
| A2-M21 | The fence character is not compared (one `longest` for both characters; the inner loop drops `runs[last][0] == run[0]`) | `test_a_fence_ends_only_on_its_own_kind_and_length[other-character]` |
| A2-M22 | The run length is not compared (`< len(run)` becomes `== 0`; the inner loop drops `len(runs[last]) >= len(run)`) | `test_a_fence_ends_only_on_its_own_kind_and_length[shorter-run]` |
| A2-M23 | The opener check rescans the later lines (`longest_after[run[0]][index] < len(run)` becomes `not any(ending[k] and runs[k][0] == run[0] and len(runs[k]) >= len(run) for k in range(index + 1, count))`) | `test_masking_takes_linear_time_on_unclosed_openers[unopened-backtick-fences, unopened-tilde-fences]` |
| A2-M24 | `_mask_quoted` returns the first draft of A2-6 (`_QUOTED.sub(lambda m: " " * len(m.group(0)), text)` with that draft's `_QUOTED`) | `test_masking_takes_linear_time_on_unclosed_openers[unopened-backtick-fences, unopened-tilde-fences, unpaired-curly-quotes]`; `test_masking_keeps_length_and_line_breaks` |
| A2-M25 | Masking blanks line breaks too (drop `if chars[index] != "\n"`) | `test_masking_keeps_length_and_line_breaks` |

Not a row: dropping the curly marker (`curly_dead_until`) gives the same results, and at the guard's size the repeated `str.find` runs in C and stays under the bound, so no bounded-time test can kill it. The linearity argument covers it, and the round-2 reviewer checks it (property 15).

Results:

Run once on the A2 overlay (the frozen head `102e8b33` with A2-1 to A2-15 and A2-19 to A2-21 applied by tool and the new file of 16.5), one mutant at a time, each file restored byte for byte, with `bf1358_a2_rows.py` (outside the repository; the runner of the first census). **25 of 25 killed**, each by the killers that the table above names; the table below lists the named killers that failed. The first draft of A2-6 is mutant A2-M24.

| ID | Verdict | Killed by |
|---|---|---|
| A2-M1 | KILLED | A2 file: `test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns[empty-text, none-result, no-response, raised]` |
| A2-M2 | KILLED | A2 file: `test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns[raised]` |
| A2-M3 | KILLED | A2 file: `test_a_reply_the_gate_accepts_dispatches_no_retry_and_is_checked` |
| A2-M4 | KILLED | A2 file: `test_the_projection_marks_a_record_that_left_a_call_out[sibling-kept]` |
| A2-M5 | KILLED | A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-only]`; A2 file: `test_the_projection_marks_a_record_that_left_a_call_out[sibling-kept, all-unverifiable, duplicate-ids]`; S2 file: `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed`; ad1295: `test_unverifiable_call_is_omitted_from_attempted[null, empty, non-string-int, non-string-list]`; ad1295: `test_duplicate_call_ids_are_uncorrelatable`; ad1295: `test_unverifiable_id_abstains_through_the_whole_pipeline[malformed-0, malformed-1, malformed-2, malformed-3, duplicate-id]` |
| A2-M6 | KILLED | A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[control-correlatable-first, control-two-empty-passes]`; A2 file: `test_the_projection_marks_a_record_that_left_a_call_out[well-formed, no-calls]`; S2 file: `test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed[record-i-found, records-search]` |
| A2-M7 | KILLED | A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-first]`; A2 file: `test_merged_with_keeps_the_incomplete_mark_in_either_order` |
| A2-M8 | KILLED | A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-last, unverifiable-between]`; A2 file: `test_merged_with_keeps_the_incomplete_mark_in_either_order` |
| A2-M9 | KILLED | A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-only, unverifiable-first, unverifiable-last, unverifiable-between]`; A2 file: `test_an_incomplete_record_round_trips_on_the_wire` |
| A2-M10 | KILLED | A2 file: `test_a_complete_record_keeps_the_ad1295_wire_shape` |
| A2-M11 | KILLED | A2 file: `test_an_incomplete_key_that_is_not_true_reads_as_no_record[false, one, string, null]` |
| A2-M12 | KILLED | A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-only, unverifiable-first, unverifiable-last, unverifiable-between]`; A2 file: `test_an_incomplete_record_round_trips_on_the_wire` |
| A2-M13 | KILLED | S2 file: `test_the_record_decides[record-incomplete]`; S2 file: `test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed`; A2 file: `test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order[unverifiable-only]` |
| A2-M14 | KILLED | S2 file: `test_the_record_decides[record-incomplete-not-a-bool]` |
| A2-M15 | KILLED | A2 file: `test_wording_quoted_over_several_lines_is_not_found[fence-with-blank-line, tilde-fence]`; A2 file: `test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged[fenced-block]`; A2 file: `test_masking_keeps_length_and_line_breaks` |
| A2-M16 | KILLED | A2 file: `test_wording_quoted_over_several_lines_is_not_found[multi-line-double-quote]`; A2 file: `test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged[multi-line-quote]`; A2 file: `test_masking_keeps_length_and_line_breaks` |
| A2-M17 | KILLED | A2 file: `test_an_unquoted_claim_beside_a_fence_or_quote_is_found[stray-quote-stops-at-blank-line]` |
| A2-M18 | KILLED | A2 file: `test_an_unquoted_claim_beside_a_fence_or_quote_is_found[unclosed-fence]`; A2 file: `test_a_fence_ends_only_on_its_own_kind_and_length[block-after-stray-opener]`; A2 file: `test_masking_takes_linear_time_on_unclosed_openers[unopened-backtick-fences]` |
| A2-M19 | KILLED | A2 file: `test_wording_quoted_over_several_lines_is_not_found[multi-line-curly]` |
| A2-M20 | KILLED | A2 file: `test_wording_quoted_over_several_lines_is_not_found[multi-line-backtick]` |
| A2-M21 | KILLED | A2 file: `test_a_fence_ends_only_on_its_own_kind_and_length[other-character]` |
| A2-M22 | KILLED | A2 file: `test_a_fence_ends_only_on_its_own_kind_and_length[shorter-run]` |
| A2-M23 | KILLED | A2 file: `test_masking_takes_linear_time_on_unclosed_openers[unopened-backtick-fences, unopened-tilde-fences]` |
| A2-M24 | KILLED | A2 file: `test_masking_takes_linear_time_on_unclosed_openers[unopened-backtick-fences, unopened-tilde-fences, unpaired-curly-quotes]` |
| A2-M25 | KILLED | A2 file: `test_masking_keeps_length_and_line_breaks` |

The scaling guards at their size (16,000 openers, 80,044 characters; 48,044 for the curly quotes): A2-M24 (the first draft of A2-6, one regex) failed them at 4.99 s (backtick fences), 10.13 s (tilde fences) and 10.00 s (curly quotes); A2-M23 (the opener check that rescans the later lines) failed them at 6.22 s and 4.70 s; the linear scanner takes about 0.05 s. Against the 2 s bound that is a margin of 2.5 to 5 times on the quadratic side and about 40 times on the linear side.

The earlier rows LC-1 to LC-4, LC-6 to LC-16 and LC-19 were rerun on the same overlay and are all KILLED. LC-5, LC-17 and LC-18 mutate lines that A2 replaces and are superseded by A2-M15 to A2-M24 and A2-M5.

Pinned files, as they stand in the overlay's working copy (sha256, and the git blob id that `git hash-object --path` gives under autocrlf; the census restored each file byte for byte):

| File | sha256 | Blob id |
|---|---|---|
| `src/probos/dm_reply.py` | `d6912c7ab438c05eb98c8cf39d7288fdcbf5e6d1a062b412cae9fd31c88a7cc8` | `aa339882d8b4b51f6e19285c897f45d0f2ac96b9` |
| `src/probos/cognitive/agentic_dispatch.py` | `bd5d3c36a8c7cee9d8a959ea2070c584e5357ebdda3ce5e002619e047969f3ab` | `db72706b10b2b9ab613dc6051b3f1c01b7e673d8` |
| `src/probos/cognitive/dm/lookup_claim.py` | `951240f60336a661dadb03aa2e365e75979a1e6ea2f1dd0b7dffd0a790934649` | `7c34598e4f9317eb72e72eb2acfbb2e24dca2a09` |
| `src/probos/cognitive/dm/reply_pipeline.py` | `4cb9b29cb7aacc61a8df446987b5df1de577c26c16edd788d5458a4ef67293df` | `87fc57304932a31e03feb966f1695c528f691689` |
| `tests/test_ad1358_s2_lookup_claim.py` | `65d852f8c9ddbc3b6e3e31780c062605dc9cd19dcf078f9cf251c516ba892915` | `3166c894b8485e90025885bd55693ea0a11198dd` |
| `tests/test_ad1358_s2_a2_repairs.py` | `29b48a8e205cf179dc86de6822ade7a8cf6f50c2116d9ccdf690b2a9e7ed9dc7` | `73a486acd378d273411942e6705121b63447e777` |
| `tests/test_ad1295_tool_success_ledger.py` | `3d4b22888b7aaa0d7f71a0ab418edf0e6f5812f1a0bc9a55bacd735e3908ffdf` | `0be79c86d976d97c8b039f4b02c5241dea4c05ba` |. If a file differs from the pinned one, rerun the rows that mutate it: M1-M3 reply_pipeline.py; M4-M6 agentic_dispatch.py; M7-M12 dm_reply.py; M13-M25 lookup_claim.py.

The focused command gains one file: `tests/test_ad1358_s2_a2_repairs.py` (E14).

### 16.11 `src/probos/cognitive/dm/lookup_claim.py` (M5)

**A2-19**
SEARCH:
```python
    if type(text) is not str or not text:
        return None
    masked = _QUOTED.sub(lambda m: " " * len(m.group(0)), text)
```
REPLACE:
```python
    if type(text) is not str or not text:
        return None
    masked = _mask_quoted(text)
```

### 16.12 `tests/test_ad1358_s2_a2_repairs.py` (M6)

**A2-20**
SEARCH:
```python
import asyncio
import logging

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome, _project_tool_invocations
from probos.cognitive.cognitive_agent import (
    _accumulate_pass_invocations,
    _attach_run_provenance,
    _build_result_metadata,
)
from probos.cognitive.dm.lookup_claim import LOOKUP_DISCLOSURE, find_lookup_claim
```
REPLACE:
```python
import asyncio
import logging
import time

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome, _project_tool_invocations
from probos.cognitive.cognitive_agent import (
    _accumulate_pass_invocations,
    _attach_run_provenance,
    _build_result_metadata,
)
from probos.cognitive.dm.lookup_claim import LOOKUP_DISCLOSURE, _mask_quoted, find_lookup_claim
```

**A2-21**
SEARCH:
```python
    assert any("lookup-claim check" in r.getMessage() for r in caplog.records) is fires
```
REPLACE:
```python
    assert any("lookup-claim check" in r.getMessage() for r in caplog.records) is fires


@pytest.mark.parametrize(("text", "expected"), [
    pytest.param(
        "~~~\nintro\n" + _FENCE + "\nI searched the records and found two games.\n" + _FENCE
        + "\nI checked the logs before answering.",
        "checked the logs", id="block-after-stray-opener",
    ),
    pytest.param(
        _FENCE + "`\nI searched the records and found two games.\n" + _FENCE + "\nThat was all.",
        "i searched", id="shorter-run",
    ),
    pytest.param(
        "~~~\nI searched the records and found two games.\n" + _FENCE + "\nThat was all.",
        "i searched", id="other-character",
    ),
])
def test_a_fence_ends_only_on_its_own_kind_and_length(text, expected) -> None:
    """A fence ends at the first later line of the same character, at least as long; a stray opener masks nothing."""
    found = find_lookup_claim(text)
    assert found is not None and expected in found.lower()


def test_masking_keeps_length_and_line_breaks() -> None:
    text = 'a "b\nc" d\n> e\n' + _FENCE + "\nf\n\ng\n" + _FENCE + "\n\u201ch\u201d `i`"
    masked = _mask_quoted(text)
    assert len(masked) == len(text)
    assert masked == "a   \n   d\n   \n   \n \n\n \n   \n" + " " * 7


@pytest.mark.parametrize("unit", [
    pytest.param(_FENCE + "a\n", id="unopened-backtick-fences"),
    pytest.param("~~~a\n", id="unopened-tilde-fences"),
    pytest.param("\u201ca ", id="unpaired-curly-quotes"),
])
def test_masking_takes_linear_time_on_unclosed_openers(unit) -> None:
    """16,000 openers that nothing ends. The linear pass takes milliseconds; the first draft of A2-6 rescanned the
    rest of the text from every fence opener (about 7 s and 12 s for the two fence kinds, measured by the
    orchestrator before round 2). The bound leaves about 20 times margin on both sides."""
    text = unit * 16_000 + "\nI searched the records and found two games."
    began = time.perf_counter()
    found = find_lookup_claim(text)
    elapsed = time.perf_counter() - began
    assert found is not None and "i searched" in found.lower()
    assert elapsed < 2.0, f"masking took {elapsed:.2f} s on {len(text)} characters"
```
