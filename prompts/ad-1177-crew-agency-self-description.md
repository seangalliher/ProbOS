# AD-1177: the crew's self-description must match the tools they actually hold

**Repo:** OSS (`d:\ProbOS`), branch `main`
**Type:** AD (new top-level). Current highest in-tree: **AD-1175**. AD-1174 (#1105) and
AD-1176 (#1107) are reserved by open issues and unbuilt. **AD-1177 is the next free number.**
**Issue:** #1109

---

## Problem

`CognitiveAgent._conversational_agentic_self_description` (AD-1070,
`src/probos/cognitive/cognitive_agent.py:2359`) tells a crew agent what it can do on a
conversational turn. It is wired (`:3346`), it is delivered whenever
`_conversational_agentic_will_run` is True, and it is well written.

It is also **stale**, and it makes a false claim.

The prose opens with `"The tools you have this turn:"` and then enumerates exactly four:
`run_python`, `search_capabilities`, `use_skill`, `delegate_task` — the set that existed when
AD-1070 shipped.

Since then the loop's assembly (`agentic_dispatch.py:1878`) grew to eleven groups:

```python
tool_ids = list(dict.fromkeys([
    *granted_ids, *mesh_ids, *mcp_ids, *exec_ids, *skill_ids,
    *search_ids, *delegate_ids, *event_log_ids, *oracle_ids,
    *publish_ids, *browser_ids,
]))
```

So an agent is handed `browser`, `oracle_query`, `publish_finding`, `event_log_query`,
`web_search`, `read_page`, `http_fetch`, plus Captain grants and MCP tools — and is told, in
prose, that it has four. The schemas are in the tool array, so the capability is reachable; the
narration above them is simply wrong, and it is the narration that sets disposition.

**This is the same defect shape as BF-701 and BF-706**: a hand-maintained declaration of a
vocabulary drifting from the vocabulary actually offered. BF-701 had three declarations and a
gate that disagreed. Here the declaration disagrees with the assembly. Both were written
correct and went stale because nothing forced them to move together.

Two secondary gaps in the same text:

1. `run_python` is described narrowly — "compute, transform data, or produce a real
   downloadable file". It is in fact the general-purpose fallback for anything the other tools
   do not cover. Nothing says so.
2. When a task needs a Python library the venv does not have, `_maybe_install_missing`
   (`tools/code_execution_tool.py:205`) returns `None` while
   `dependency.dynamic_install_enabled` is False (the shipped default and the current live
   setting), the script runs, and the model receives a raw `ModuleNotFoundError` traceback with
   no indication that an approval path exists. The acquisition half of this is **AD-1178** and
   is NOT in scope here; this AD only ensures the agent is told to name what it needs.

**Captain's framing (2026-08-01):** crew agents should have agency comparable to Claude Code or
GitHub Copilot — resourceful, willing to reach for what is there — while respecting the chain
of command. Today's block under-describes what they hold, which is a brake on exactly the
emergent, collaborative behaviour ProbOS exists to produce.

---

## Decision

Rewrite the body of `_conversational_agentic_self_description` so it:

1. **Stops enumerating a fixed tool subset.** The tool array the model receives is the
   authoritative list; the prose points at it instead of competing with it. This removes the
   drift class permanently rather than refreshing a list that will go stale again.
2. **Frames `run_python` as the general-purpose instrument** — the thing to reach for when the
   task fits none of the other tools — while keeping the file-production example, which is
   concrete and works.
3. **Keeps `search_capabilities` named**, because discovering what is reachable is a distinct
   act the model must know to perform, not just a tool to call.
4. **Names the acquisition path**: when something needed is absent, state plainly what is
   needed and continue with what is at hand.
5. **States the chain-of-command boundary** in the same breath as the resourcefulness, so the
   two read as one instruction rather than as competing pressures.

Keep the existing contract exactly: returns `""` when
`_conversational_agentic_will_run(observation)` is False, so every single-pass turn stays
byte-identical. Keep it overridable. Keep it gap-regex-safe.

### Gap-regex constraint (hard)

The returned text MUST NOT match `_CAPABILITY_GAP_RE` (`cognitive/decomposer.py:33`). Read the
real regex before writing prose. Specific traps in this AD's subject matter:

- `no (?:built-in |native )?(?:capability|ability|support|way|mechanism|tool)` — so **"no tool"
  is forbidden**. "fits none of the other tools" is safe; "when no tool fits" is not.
- `lack(?:s|ing)?` — do not use "lack" in any form.
- `not (?:available|supported|possible)` — do not describe a missing library this way.
- `don't have` / `doesn't have` / `cannot` / `can't` / `unable to` — all forbidden.

The test suite must assert this directly by importing the real `is_capability_gap`.

---

## Target files

| File | Change |
|---|---|
| `src/probos/cognitive/cognitive_agent.py` | Rewrite the return body of `_conversational_agentic_self_description` (`:2359`). Update its docstring to describe the new contract. **Do not touch the gate, the call site at `:3346`, or any sibling hook.** |
| `tests/test_ad1177_crew_agency.py` | NEW. See acceptance criteria. |

---

## Acceptance criteria

Add `tests/test_ad1177_crew_agency.py`. Follow the fixture style of
`tests/test_ad1070_capability_suppression.py` (it already builds a DM agent and drives this
exact hook — reuse its helpers rather than inventing new ones).

Required tests:

1. **Byte-identical when the loop will not run.** With `dm_agentic.enabled` False, and
   separately for a group turn and a vision turn, the hook returns `""`. Three cases.
2. **Renders on a 1:1 DM when the loop will run.** Non-empty, and contains the affirmative
   disposition.
3. **Gap-regex-safe.** `from probos.cognitive.decomposer import is_capability_gap` and assert
   `is_capability_gap(block) is False`. Import the real function — do not re-implement the
   regex.
4. **THE DRIFT GUARD (the headline test).** Assert the block does **not** hard-code a tool
   enumeration that can drift from the assembly. Concretely: collect the tool ids the
   conversational path can offer (`run_python`, `use_skill`, `search_capabilities`,
   `delegate_task`, `event_log_query`, `oracle_query`, `publish_finding`, `browser`,
   `web_search`, `read_page`, `http_fetch`) and assert the block does not present a bulleted
   list that names some of them while omitting others. The property to pin is: **either every
   offerable tool id appears, or the block defers to the tool array.** Write the assertion so
   it fails if a future edit reintroduces a partial hand-written list. State the property in
   the test docstring so its intent survives.
5. **`run_python` is framed as the general fallback**, not only as a file producer — assert the
   fallback framing is present.
6. **`search_capabilities` is still named.**
7. **Chain of command is stated** — assert the approval/orders clause is present.
8. **Overridable** — a subclass returning `""` is respected (Open/Closed, matching the sibling
   hooks' tests).

Expected: **10–12 new tests.**

### Regression gates (run before the full suite)

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1177_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest `
  tests/test_ad1177_crew_agency.py `
  tests/test_ad1070_capability_suppression.py `
  tests/test_ad1070a_artifact_suppression.py `
  tests/test_ad1065_conversational_agentic.py `
  tests/test_ad1028_golden_prompt.py `
  -q -n 0
```

The **AD-1028 golden prompt test is the one most likely to red** — it captures a composed
prompt. Check whether it captures with `perception.enabled=False` and a single-pass turn (in
which case this hook returns `""` and the golden is unaffected). If the golden does cover an
agentic turn, regenerate it deliberately and say so in the report — do not silently accept a
changed golden.

Then one full gate:

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1177_full_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q --timeout=600
```

Baseline is **22,436 passed / 34 skipped**. Reconcile the new total exactly against the number
of tests added and report the arithmetic.

---

## Do NOT build in this AD

Named explicitly, because each is tempting and each is separately tracked:

- **Do not** change `_conversational_agentic_will_run` or any gate. The dispatch contract is
  out of scope.
- **Do not** touch the dependency-install path or `_maybe_install_missing`. That is **AD-1178**.
- **Do not** generate tool schemas from tool objects. That is **AD-1179**.
- **Do not** change the tool assembly in `agentic_dispatch.py`. No new tools are offered here.
- **Do not** widen `_BROWSER_LOOP_ACTIONS`. BF-706 settled the browser surface; the read-only
  loop offer is deliberate and applies only to agents that were not granted `browser`.
- **Do not** touch `standing_orders.py` / `compose_instructions`. The change belongs in the
  hook.
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap in the code commit.
- **Do not** stage `config/system.yaml` — it is skip-worktree. Arming happens separately.

---

## Notes for the Builder

- **Stage before running the full gate.** `test_ad1123_bounded_federation_relay.py` inspects
  *unstaged* `git diff --name-only`. This AD touches neither `events.py` nor `types.py`, so it
  should not fire — but stage anyway; it costs nothing and a false red costs fifteen minutes.
- The str-replace trap that bit twice this week: whatever appears at either **end** of your
  `oldString` must reappear in `newString` unless you mean to delete it. A trailing bare newline
  joins the following line.
- Do not add a new config flag. This hook is already gated by `dm_agentic.enabled` through
  `_conversational_agentic_will_run`; a second flag would be a second thing to leave off.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
