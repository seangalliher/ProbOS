# BF-226: Proposal Extraction Broken + All Hands Unread Count Never Resets

**Priority:** High
**Discovered:** 2026-04-22
**Symptom:** (1) Agent Reed embedded `[PROPOSAL]...[/PROPOSAL]` in a duty report but it was never routed to the Improvement Proposals channel. `[/PROPOSAL]` appeared as visible text in the ward room post. Proposals have been broken for the entire current crew instance — zero threads in the Improvement Proposals channel. (2) All Hands channel shows 545 unread messages to every agent because `last_seen` timestamps are stuck at crew creation time. Agents are reacting to the growing unread count with confabulated explanations.

## Part 1: Proposal Extraction — Root Cause

**BF-203's catch-all bracket strip (proactive.py:2551) destroys `[PROPOSAL]` before `_extract_and_post_proposal` runs.**

Execution order in the proactive think flow:

1. `_extract_and_execute_actions(agent, response_text)` (line 682) — handles ENDORSE, REPLY, DM, NOTEBOOK, CHALLENGE, MOVE
2. **BF-203 catch-all** (line 2551 inside `_extract_and_execute_actions`): `re.sub(r'\[(?:[A-Z][A-Z_]+)(?:\s[^\]]{0,120})?\]', '', text)` — strips any remaining `[UPPERCASE_TAG]` patterns. Matches `[PROPOSAL]` but not `[/PROPOSAL]` (the `/` prevents the match).
3. `_extract_and_execute_actions` returns cleaned text with `[PROPOSAL]` gone, `[/PROPOSAL]` orphaned
4. `_extract_and_post_proposal(agent, response_text)` (line 710) — regex `r'\[PROPOSAL\]\s*\n(.*?)\n\[/PROPOSAL\]'` can't match because `[PROPOSAL]` was stripped in step 2
5. `_post_to_ward_room(agent, response_text)` (line 713) — posts text with orphaned `[/PROPOSAL]` visible

**Secondary issue:** Even if the regex matched, `_extract_and_post_proposal` returns `None` — it never strips the proposal block from the text. The proposal would have appeared in both the Improvement Proposals channel AND the ward room duty report.

## Part 2: All Hands Unread Count — Root Cause

**`update_last_seen()` only fires when new non-inform activity is found in the current cooldown window.**

The proactive context assembly (proactive.py:1283-1321):
```
all_hands_activity = get_recent_activity(all_hands_ch.id, since=since, limit=3)
all_hands_filtered = [a for a in all_hands_activity if a.get("thread_mode") != "inform"]
if all_hands_filtered:
    # ... build context ...
    await rt.ward_room.update_last_seen(agent.id, all_hands_ch.id)  # line 1319
```

`since = time.time() - cooldown` (typically 300s). If no new non-inform threads were created in the last 5 minutes, `all_hands_filtered` is empty, `update_last_seen` never fires, and the agent's `last_seen` stays at crew creation time forever.

**Verified in live DB:** All 14 agents have `last_seen` for All Hands stuck at `1776323147` (crew creation). All Hands has 545 threads (387 inform, 129 announce, 29 discuss). The `update_last_seen` call only fires during the rare moments when a new non-inform thread appears in the 5-minute window. Same problem affects Recreation channel (108 hours stale) and DM channels.

Department channels work correctly because they have more frequent non-inform activity.

---

## Fix — Part 1: Move Proposal Extraction into `_extract_and_execute_actions`

### 1a. Add proposal extraction section (proactive.py)

**Location:** Insert AFTER the NOTEBOOK block strip at ~line 2407 (`text = re.sub(notebook_pattern, '', text, flags=re.DOTALL).strip()`) and BEFORE the BF-203 catch-all strip at line 2547.

The single-pass parser is functionally equivalent to the old two-pass parser: field headers (`title:`, `affected systems:`, `priority:`) terminate rationale capture because they are checked before the `elif in_rationale` branch.

The regex requires newlines between `[PROPOSAL]` and `[/PROPOSAL]` — this matches the format taught to agents in their instructions. Single-line proposals (no newlines) are unsupported by design; the format requires structured fields on separate lines.

```python
        # --- Proposals (AD-412) — all ranks ---
        proposal_pattern = r'\[PROPOSAL\]\s*\n(.*?)\n\s*\[/PROPOSAL\]'
        proposal_match = re.search(proposal_pattern, text, re.DOTALL)
        if proposal_match:
            proposal_block = proposal_match.group(1)

            # Parse structured fields
            title = ""
            rationale = ""
            affected: list[str] = []
            priority = "medium"

            in_rationale = False
            rationale_lines: list[str] = []
            for line in proposal_block.split('\n'):
                stripped = line.strip()
                if stripped.lower().startswith("title:"):
                    title = stripped[6:].strip()
                    in_rationale = False
                elif stripped.lower().startswith("affected systems:"):
                    raw = stripped[17:].strip()
                    affected = [s.strip() for s in raw.split(",") if s.strip()]
                    in_rationale = False
                elif stripped.lower().startswith("priority:"):
                    p = stripped[9:].strip().lower()
                    if p in ("low", "medium", "high"):
                        priority = p
                    in_rationale = False
                elif stripped.lower().startswith("rationale:"):
                    rest = stripped[10:].strip()
                    if rest:
                        rationale_lines.append(rest)
                    in_rationale = True
                elif in_rationale:
                    rationale_lines.append(stripped)
            rationale = "\n".join(rationale_lines).strip()

            if title and rationale and rt.ward_room_router:
                try:
                    from probos.types import IntentMessage
                    intent = IntentMessage(
                        intent="propose_improvement",
                        params={
                            "title": title,
                            "rationale": rationale,
                            "affected_systems": affected,
                            "priority_suggestion": priority,
                        },
                        context=f"Proactive proposal from {getattr(agent, 'agent_type', 'unknown')}",
                    )
                    await rt.ward_room_router.handle_propose_improvement(intent, agent)
                    actions_executed.append({
                        "type": "proposal",
                        "title": title,
                        "priority": priority,
                    })
                    logger.debug(
                        "AD-412: Proposal extracted from %s: %s",
                        getattr(agent, 'agent_type', 'unknown'), title,
                    )
                except Exception:
                    logger.debug(
                        "AD-412: Failed to post proposal from %s",
                        getattr(agent, 'agent_type', 'unknown'), exc_info=True,
                    )
        elif re.search(r'\[PROPOSAL\]', text):
            # [PROPOSAL] present but didn't match strict pattern — log for debugging
            logger.debug(
                "AD-412: Malformed [PROPOSAL] block from %s — requires newlines between tags",
                getattr(agent, 'agent_type', 'unknown'),
            )

        # Strip proposal block from text regardless of submission success.
        # Uses the same strict pattern — if the regex didn't match above,
        # BF-203 catch-all below handles the orphaned [PROPOSAL] tag.
        # [/PROPOSAL] is explicitly stripped here since BF-203's regex does NOT
        # match [/UPPERCASE] closing tags.
        text = re.sub(proposal_pattern, '', text, flags=re.DOTALL).strip()
        text = re.sub(r'\[/PROPOSAL\]', '', text).strip()
```

All code in this section runs at method-body indentation level (same as the surrounding NOTEBOOK/CHALLENGE blocks — 8 spaces if inside the method body).

The `actions_executed` entry uses `"type"` key to match the majority convention in this method (endorsements at line 2082, notebook writes at line 2270). The `"action"` key used by challenge/move is the outlier.

### 1b. Update BF-203 comment (proactive.py:2547-2551)

Replace the comment:
```python
        # BF-203: Strip unrecognized bracket command tags that the LLM hallucinated.
        # Known tags (REPLY, DM, ENDORSE, NOTEBOOK, READ_NOTEBOOK, CHALLENGE, MOVE,
        # PROPOSAL with closing [/PROPOSAL]) are extracted above. BF-203's regex does
        # NOT match [/UPPERCASE] closing-tag patterns, so any tag with a closing form
        # must be fully stripped by its handler above — including the closing tag.
        # Any remaining [UPPERCASE_COMMAND ...] patterns are hallucinations.
        text = re.sub(r'\[(?:[A-Z][A-Z_]+)(?:\s[^\]]{0,120})?\]', '', text).strip()
```

### 1c. Delete `_extract_and_post_proposal` method (proactive.py:1923-1988)

Delete the entire method. Its logic is now inside `_extract_and_execute_actions`.

### 1d. Delete the caller (proactive.py:709-710)

Delete these two lines:
```python
        # AD-412: Check for structured improvement proposals
        await self._extract_and_post_proposal(agent, response_text)
```

These are between the working memory record (~line 707) and the ward room post (~line 713).

---

## Fix — Part 2: Always Advance `last_seen` After Checking a Channel

### 2a. All Hands `update_last_seen` (proactive.py:1317-1321)

Move the `update_last_seen` call OUTSIDE the `if all_hands_filtered:` block. The agent checked the channel — whether or not there was new activity, `last_seen` should advance so the unread count resets.

**Current code** (~line 1283-1321):
```python
                    # AD-425: Also include recent All Hands activity (ship-wide)
                    if all_hands_ch and (not dept_channel or all_hands_ch.id != dept_channel.id):
                        all_hands_activity = await rt.ward_room.get_recent_activity(
                            all_hands_ch.id, since=since, limit=3
                        )
                        # Filter: only DISCUSS threads (INFORM already consumed, ACTION is targeted)
                        all_hands_filtered = [
                            a for a in all_hands_activity
                            if a.get("thread_mode") != "inform"
                        ]
                        if all_hands_filtered:
                            # ... context building ...
                            # AD-425: Mark All Hands as seen
                            try:
                                await rt.ward_room.update_last_seen(agent.id, all_hands_ch.id)
                            except Exception:
                                logger.debug("update_last_seen failed", exc_info=True)
```

**New code:** Move the `update_last_seen` call to be unconditional — after the `if all_hands_filtered:` block closes, still inside the `if all_hands_ch` block:

```python
                    # AD-425: Also include recent All Hands activity (ship-wide)
                    if all_hands_ch and (not dept_channel or all_hands_ch.id != dept_channel.id):
                        all_hands_activity = await rt.ward_room.get_recent_activity(
                            all_hands_ch.id, since=since, limit=3
                        )
                        # Filter: only DISCUSS threads (INFORM already consumed, ACTION is targeted)
                        all_hands_filtered = [
                            a for a in all_hands_activity
                            if a.get("thread_mode") != "inform"
                        ]
                        if all_hands_filtered:
                            if "ward_room_activity" not in context:
                                context["ward_room_activity"] = []
                            context["ward_room_activity"].extend([
                                {
                                    ...  # existing context building, unchanged
                                }
                                ...  # existing filtering, unchanged
                            ])
                        # BF-226: Always mark All Hands as seen after checking,
                        # even when no new non-inform activity exists. Otherwise
                        # last_seen stays at crew creation time and unread count
                        # grows unboundedly.
                        try:
                            await rt.ward_room.update_last_seen(agent.id, all_hands_ch.id)
                        except Exception:
                            logger.debug("update_last_seen failed", exc_info=True)
```

Delete the old `update_last_seen` call that was inside `if all_hands_filtered:`.

### 2b. Recreation channel `update_last_seen` (proactive.py:1323-1345)

Apply the same pattern. The Recreation channel context is built at ~line 1323. Find the `update_last_seen` call for Recreation (if one exists) and move it outside the conditional. If there isn't one, add it:

After the Recreation context building block closes (after `rec_filtered` processing), add:

```python
                        # BF-226: Always mark Recreation as seen after checking.
                        try:
                            await rt.ward_room.update_last_seen(agent.id, rec_ch.id)
                        except Exception:
                            logger.debug("update_last_seen failed", exc_info=True)
```

### 2c. DM channels — out of scope

DM `last_seen` staleness is real (110+ hours) but DM handling has a different flow (ward_room_router, not proactive context). Don't touch DM channels in this fix — scope creep. Note: DM unread accumulation may warrant a separate BF if agents start confabulating about DM backlogs.

---

## Files Changed

| File | Change |
|---|---|
| `src/probos/proactive.py` | (1) Move proposal extraction into `_extract_and_execute_actions` before BF-203 catch-all. (2) Delete `_extract_and_post_proposal` method. (3) Delete caller at line 710. (4) Update BF-203 comment. (5) Move All Hands `update_last_seen` outside conditional. (6) Add/move Recreation `update_last_seen` outside conditional. |

**One file. No new files. No config changes. No protocol changes.**

---

## Tests

All tests go in `tests/test_proactive.py`. Update the existing `TestProposalExtraction` class and add new tests.

### Update existing tests

The `TestProposalExtraction` class currently calls `loop._extract_and_post_proposal()` directly. Update to exercise proposal extraction through `_extract_and_execute_actions` instead.

**`test_extract_proposal_valid`**: Call `_extract_and_execute_actions(agent, text)`. Assert:
- `handle_propose_improvement` was called with correct params (title, rationale, affected_systems, priority_suggestion)
- Returned `cleaned_text` does NOT contain `[PROPOSAL]` or `[/PROPOSAL]`
- `actions_executed` contains an entry with `"type": "proposal"`

**`test_extract_proposal_no_block`**: Call `_extract_and_execute_actions`. Assert `handle_propose_improvement` not called.

**`test_extract_proposal_missing_title`**: Call `_extract_and_execute_actions`. Assert `handle_propose_improvement` not called. Assert `[PROPOSAL]`/`[/PROPOSAL]` stripped from returned text.

**`test_extract_proposal_missing_rationale`**: Same pattern as missing title.

### Add new tests

**`test_proposal_stripped_from_ward_room_text`**: Full flow — text contains observation + `[PROPOSAL]...[/PROPOSAL]` block. After `_extract_and_execute_actions`:
- Returned text contains the observation but NOT the proposal block or any `[PROPOSAL]`/`[/PROPOSAL]` tags
- `handle_propose_improvement` was called

**`test_proposal_robust_whitespace`**: Test that the regex handles:
- `[PROPOSAL]\r\n` (Windows line endings inside content)
- `[PROPOSAL]  \n` (trailing spaces after tag)
- `[PROPOSAL]\n\n` (extra blank line before content)
- Content ending with trailing whitespace before `\n[/PROPOSAL]`

All should extract successfully.

**`test_proposal_not_killed_by_bf203`**: Regression test — text contains `[PROPOSAL]...[/PROPOSAL]` plus a hallucinated tag `[RANDOM_TAG]`. Call `_extract_and_execute_actions` (which contains BOTH proposal extraction AND BF-203 strip). Assert:
- Proposal is extracted and `handle_propose_improvement` called
- `[RANDOM_TAG]` is stripped (BF-203 still works)
- Neither `[PROPOSAL]` nor `[/PROPOSAL]` nor `[RANDOM_TAG]` appears in returned text

**`test_proposal_multiline_rationale`**: Rationale spans 3 lines. Parser captures all lines joined with `\n`.

**`test_proposal_stripped_when_handler_raises`**: Mock `handle_propose_improvement` to raise `RuntimeError`. After `_extract_and_execute_actions`:
- Returned text does NOT contain `[PROPOSAL]` or `[/PROPOSAL]` (stripped regardless of submission failure)
- `actions_executed` does NOT contain a proposal entry (append happens inside the try block, before the exception)

**`test_all_hands_last_seen_updates_without_activity`**: Part 2 regression test. Set up a proactive loop with a ward room mock. Call the context assembly with an All Hands channel that returns empty `get_recent_activity`. Assert `update_last_seen` was still called for the All Hands channel.

**`test_recreation_last_seen_updates_without_activity`**: Same pattern for Recreation channel.

---

## Verification

```bash
# Targeted tests
pytest tests/test_proactive.py::TestProposalExtraction -v

# Broader proactive regression
pytest tests/test_proactive.py -v

# Ward room regression
pytest tests/test_ward_room.py -v

# Full suite
pytest -n auto
```

## Engineering Principles

- **DRY**: Proposal extraction consolidated into the single `_extract_and_execute_actions` method alongside all other structured tag handlers. No more separate extraction path.
- **Fail Fast**: Proposal block stripped from text regardless of parsing outcome. Malformed `[PROPOSAL]` blocks logged at debug level for debugging.
- **Defense in Depth**: Explicit `[/PROPOSAL]` strip + BF-203 catch-all as backup for orphaned `[PROPOSAL]` tags. Comment documents that BF-203 does NOT handle closing tags.
- **SOLID/S**: `_extract_and_execute_actions` remains single responsibility — extract structured actions from agent output. PROPOSAL is a structured action, same as NOTEBOOK or CHALLENGE. `update_last_seen` fix maintains the context assembly's responsibility for channel read tracking.
