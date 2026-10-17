**Drafted by:** `claude-architect` (Claude Code, Opus 5.5; read-only consult through `scripts/claude_architect.py`, saved verbatim by the orchestrator), 2026-10-17
**Status:** ready to build as one docs and test change. The consult's bridge exit was 4: three of its Bash calls were denied (a grep of the handoff and two greps of `events.jsonl`); the answer cites evidence read by other tools and matches the orchestrator's own probe of the session file (355 `agent` and 1 `user` usage records of type `conversation-agent`, 205 of type `conversation-subagent`).
**Provenance note:** this is the Architect's answer to the Captain's three queued profile follow-ups (a plain-id `model:` in both profiles, explicit delegation models, the model guard; F-91, F-116 and F-117 on #1523) with its decisions D1 to D6, the guard paragraph, the replacement sentences and the test plan. Session `176316bf-f1ef-4fa3-b643-e1151de50d1e`, effort high.

# Consult: explicit delegation models, plain-id profile models and the orchestrator's model guard (F-91, F-116 and F-117 on #1523)

**Verdict:** go, with four changes to D2. The id form does not protect anything here; the guard does. Under the VS Code host the plain id is undocumented. If it fails to resolve, the guard stops the session at its first check (fail-closed), and the Captain decides whether to revert.

Read-only consult: I edited no repository file. I wrote one note to my agent memory (`.claude/agent-memory/claude-architect/reference_copilot_session_events.md` plus its index line).

## Decisions

| # | Decision | Reason / evidence |
|---|---|---|
| **D1** | **Confirmed.** The profile carries the plain id only. A fallback is another GPT model, passed explicitly as the call's `model` and named in the report, and the guard applies to it. Constitution line 48: "then change model (" becomes "then pass another GPT model explicitly as the call's `model` and name it in the report (". | VS Code documents an array as an ordered fallback ("tries each model in order until an available one is found"). But the incident shows that a silent fallback is the hazard, and explicit delegation makes the profile default unused for every delegated call. |
| **D2** | **Confirmed, with four changes.** (1) Filter own-model records on `interactionType` = `conversation-agent`, not `initiator` = `agent`: the Captain's turns are recorded as `"initiator":"user","interactionType":"conversation-agent"` (events.jsonl:15). The other 340 such records are `agent`, and none in `conversation-agent` is on a non-Claude model. (2) At session start fewer than 3 records may exist; check all of them. (3) Do not use `subagent.started`: it carries only the requested `model`/`taskModelSource` (events.jsonl:222). The proof is the first sub-agent usage record and `subagent.completed.firstDispatchedModel` (events.jsonl:1763; `toolCallId` there equals `parentToolCallId` in records such as line 240). (4) "Stop waiting/kill" cannot be implemented, because there is no kill. Use instead: a reviewer is relaunched; a Builder is let to end, its changes are discarded back to the tree in its brief, then it is relaunched; a second miss counts as an own-model miss (stop). | Verified in the live session file. Compaction is `session.compaction_complete` (line 7137). The handoff path is named nowhere in the repo, so the text names `d:/ProbOS/logs/orchestrator-handoff.md`. |
| **D3** | **Confirmed.** One sentence goes in the guard; no edits to the mode lists. | Line 64 already allows a stop for "an irreducible external blocker", and a model the runtime will not dispatch is one. Line 119's "Stop only when" governs parks, not this stop. |
| **D4** | **Confirmed (a)–(d), plus:** a planted-negative test for the regex (the file's own premise-first rule, lines 18-21). In (b), also tie the reviewer id to both the guard and the constitution. | See the test plan. |
| **D5** | **A contract is needed:** `prompts/explicit-delegation-models-and-model-guard.md`. The orchestrator saves the "Final text" and "Test plan" below verbatim, under `**Drafted by:** \`claude-architect\` (Claude Code, Opus 5.5), 2026-10-17`, and commits it alone first. Add DECISIONS and PROGRESS entries with no AD or BF number. | Both precedents had contracts (`prompts/review-rounds-and-progress-comments.md`, DECISIONS.md:106). The Diff Reviewer needs a written claim to review against. The DECISIONS entry must say it supersedes the display-name choice at DECISIONS.md:116. |
| **D6** | See the table below. | Grep over `CLAUDE.md`, `.claude/agents/claude-architect.md`, `.github/**`, `docs/development/**`, `scripts/`, `tests/`, `src/`. |

**D6: what changes and what does not**

| Location | Action |
|---|---|
| `.github/copilot-instructions.md:46` | Change (replacement below). |
| `.github/copilot-instructions.md:48` | Change ("then change model", per D1). |
| `CLAUDE.md:48` "pins GPT models" | Change, because "models" is plural and the array is going. New wording: "The Copilot `Diff Reviewer` runs on a GPT model (`gpt-6.1-sol`, passed explicitly on each call) so the reviewer is a different model family from a Claude author." |
| `CLAUDE.md:33` "GPT-6.1 Sol Diff Reviewer" | Keep. It names the model in prose, not the front-matter form. |
| `copilot-instructions.md:50` (GPT-6 Sol / GPT-6.1 Sol) | Keep. It records a past measurement. |
| `diff-reviewer.agent.md` body | No change. Only line 103 ("Some reviewer models") mentions models, and it is generic. |
| `claude-architect.md` | No change. Its only `model` hits are its own front matter (`claude-opus-5-5`) and line 93. |
| `DECISIONS.md:116` | Do not edit, because it is history. The new entry supersedes it. |
| `docs/development/*` | Nothing relevant: the roadmap "different model" hits are product ADs, and the `claude-sonnet-5.5` hits in the config docs are product config. |
| `scripts/`, `src/` | No consumer of either profile's `model` (only `tests/test_standing_orders_layout.py`). |

**Front matter:** `model: "claude-sonnet-5.5"` and `model: "gpt-6.1-sol"` (quoted, like the current orchestrator style).

**Blind spot to put in the PR body.** VS Code's custom-agents page defines `model` as a string or an ordered array, and its examples use display names (`['Claude Opus 4.5', 'GPT-5.2']`). The qualified `Name (vendor)` form is specified only for `handoffs.model`, and plain ids are not documented. So after merge, check in a fresh session:
1. The orchestrator session's first `conversation-agent` record.
2. A Diff Reviewer launched with no model argument, and its `firstDispatchedModel`.

If either shows Auto, reverting that file to the display name reverses item 1 of the Captain's directive. That is the Captain's decision: escalate it as a one-line choice.

## Final text: the guard paragraph

Insert it after line 18 of the orchestrator profile, as its own paragraph. It is about 1,950 characters.

```markdown
**Explicit models and the model guard (Captain, 2026-10-17; F-116 and F-117 on #1523).** Never leave a delegation's model to a default. Pass `model: "claude-sonnet-5.5"` on every Builder call and `model: "gpt-6.1-sol"` on every Diff Reviewer call; a reviewer fallback is another GPT model, passed the same way and named in the report. An explicit model is necessary, not sufficient: on 2026-10-17 an unpinned reviewer ran on `gpt-6-luna` and the orchestrator went on to change the main checkout on `mai-code-1.1-flash`, and a session on Auto recorded `explicit_override` for `gpt-6.1-sol` yet dispatched on `gpt-6-luna`. The evidence is this session's `events.jsonl` under `~/.copilot/session-state/<session id>/`; read only lines that start with `{"type":"session.usage_record"` or `{"type":"subagent.`, because the same strings occur inside messages.
1. **Your own model.** Before the first delegation, after every delegation returns and after every compaction, take the last 3 usage records whose `interactionType` is `conversation-agent` (fewer at the start of a session; a delegate's records are `conversation-subagent` and do not count). Each must show `"model":"claude-sonnet-5.5"` and `"isAuto":false`. If one does not, write the handoff (`d:/ProbOS/logs/orchestrator-handoff.md`: state, in-flight items, next step) and stop. The stop holds in Backlog Burn-Down and Delegated AD Execution Mode as well; never continue on another model.
2. **The delegate's model.** Its usage records (`parentToolCallId` equal to the delegating tool call) must show the model you passed with `"isAuto":false`, and its `subagent.completed` must show it as `firstDispatchedModel`; `subagent.started` shows only the request. For a background delegate, read its first record from a 120-second watchdog after launch. A review on another model is not a round: relaunch it. A Builder on another model: let it end, discard its changes back to the tree in its brief, and relaunch. If the relaunch also misses, treat it as a miss under 1.
```

## Replacement for the line-46 sentence

> Invoke it with a different model than the one that wrote the code: pass `gpt-6.1-sol`, the model `.github/agents/diff-reviewer.agent.md` names, as the call's `model` every time, because a profile's model is only a default (the author is usually Claude).

The two sentences that follow it ("A second read…", "Tell it what…") stay unchanged. The change adds about 45 bytes to a 14,771-byte file (cap 18,000).

## Test plan (`tests/test_standing_orders_layout.py`, run with `-n 0`)

1. **Add** `PLAIN_MODEL_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")`. Replace the comment and `KNOWN_ARRAY` at lines 94-95 with it.
2. **`test_plain_model_id_pattern_rejects_display_names`**: it accepts `gpt-6.1-sol` and `claude-sonnet-5.5`. It rejects `GPT-6.1 Sol (copilot)`, `Claude Sonnet 5.5 (copilot)`, `GPT-6.1 Sol`, `gpt-6.1-sol (copilot)` and `""`.
3. **`test_agent_profile_models_are_plain_ids`** replaces `test_agent_profile_models_are_strings` (lines 407-415). There must be at least 2 profiles, and each `.github/agents/*.agent.md` must have a `model` that is a `str` matching `PLAIN_MODEL_ID`. The failure lists the offenders.
4. **Delete** `test_known_array_model_exceptions_are_still_arrays` (lines 418-423).
5. **`test_model_guard_quotes_the_profile_ids`**: read `o = model(ORCHESTRATOR)` and `r = model(diff-reviewer)` from the front matter, then assert:
   - the orchestrator text contains f'`"model":"{o}"`';
   - it contains f'`model: "{r}"` on every Diff Reviewer call';
   - the constitution contains f"`{r}`";
   - the guard heading's index lies between "**Delegate synchronously when the next step needs the result.**" and "**Overlap waiting with read-only preparation".
6. **Add to `PROCEDURE`**:
   - `"**Explicit models and the model guard (Captain, 2026-10-17"`
   - `"on every Builder call"`
   - ``"whose `interactionType` is `conversation-agent`"``
   - ``"`firstDispatchedModel`"``
   - `"A review on another model is not a round"`

   None of these is in the constitution today: `firstDispatchedModel` has no hit under `.github/`, and the line-46 replacement contains none of them.
7. **Unchanged, and must still pass:** `test_orchestrator_profile_frontmatter_has_cli_shape`, `test_no_sentence_is_duplicated_across_instruction_files`, `test_constitution_stays_slim` and `test_constitution_prefix_delivered_to_the_native_builder`.
8. **Mutations, each of which must fail at least one test:**
   - revert the reviewer `model` to the array (test 3);
   - set the orchestrator `model` to `"Claude Sonnet 5.5 (copilot)"` (tests 3 and 5);
   - change `claude-sonnet-5.5` in the guard (test 5);
   - drop the guard paragraph (tests 5 and 6);
   - copy a guard needle into the constitution (`test_orchestrator_profile_carries_the_procedure`).

## Not verified from the repository

- The 04:36Z and 05:24Z incident details and the CLI 1.0.99 probe: I relied on the orchestrator's evidence. I did read the field shapes in the live `events.jsonl`.
- How VS Code resolves the plain id: only the post-merge probe can show it.
- `gh issue view 1523` confirmed the text of F-91.

Sources:
- [VS Code: custom agents](https://code.visualstudio.com/docs/agent-customization/custom-agents)
- [awesome-copilot: Building Custom Agents](https://awesome-copilot.github.com/learning-hub/building-custom-agents/)
