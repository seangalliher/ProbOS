# AD-1180: the agentic disposition must reach every path that hands out tools

**Repo:** OSS (`d:\ProbOS`), branch `main`
**Type:** AD (new top-level). Highest assigned: **AD-1179** (issue #1111, unbuilt).
AD-1177 shipped at `2d04770b`. **AD-1180 is the next free number.**
**Issue:** #1112

---

## Problem

AD-1177 gave crew agents a disposition — read your tool array, `run_python` is the
general-purpose instrument, be resourceful and retry, act inside your orders. It works, and it
reaches exactly **one** execution path.

The disposition lives in `CognitiveAgent._conversational_agentic_self_description`
(`cognitive_agent.py:2359`), which is composed into the prompt only on the Captain's 1:1 DM
turn. Every other agentic path passes the agent's **static** `instructions` attribute straight
through:

| Call site | `instructions` passed | Gets the disposition |
|---|---|---|
| `cognitive_agent.py:3785` (conversational) | `system_prompt` — the **composed** prompt | **Yes** |
| `cognitive_agent.py:1650` (task path) | `getattr(self, "instructions", "")` | No |
| `crew_executor.py:1734` (crew children) | `str(getattr(agent, "instructions", "") or "")` | No |
| `crew_verifier.py:1168` (convergence re-run) | `instructions` param, static upstream | No |
| `delegate_task_tool.py:184` (delegation) | `getattr(target, "instructions", "")` | No |

`WorkItemAgenticExecutor.run` passes `system_prompt=instructions or ""` to the loop
(`agentic_dispatch.py:1998`) with no composition of its own.

**The consequence is the sharp part.** All five call sites go through the *same*
`WorkItemAgenticExecutor.run`, which assembles the *same* eleven tool groups. So crew children,
the verifier and delegated sub-agents each receive a full tool array — `run_python`, `browser`,
`oracle_query`, `publish_finding`, the mesh reads — and **zero** disposition about using any of
it. That is precisely the gap AD-1177 was written to close, sitting untouched in the paths where
autonomous work actually happens.

**Captain's goal (2026-08-01):** *"an environment that encourages emergent behavior and
collaborative intelligence."* Emergence and collaboration live in crew fan-out, delegation and
convergence — none of which AD-1177 reached. It made agents more resourceful only while the
Captain is personally talking to them, which is close to the opposite of autonomy.

`scout.py:543` is **not** in scope: it calls `ProcessChainExecutor.run`, a different class.

---

## Decision

Move the disposition text to a shared leaf module and compose it at the **single choke point**
every agentic path already flows through, rather than duplicating prose into five call sites.

1. **New leaf module `src/probos/cognitive/agentic_disposition.py`** holding the disposition as
   a module-level constant. No imports beyond stdlib — it must stay import-cycle-safe.
   (Verified: `agentic_dispatch.py` has no module-level import of `cognitive_agent.py`, and
   `cognitive_agent.py` imports `WorkItemAgenticExecutor` only *inside* methods at `:1647` and
   `:3730`. A leaf constant module is safe from both.)

2. **`_conversational_agentic_self_description` returns that constant**, unchanged in content.
   This is a pure extraction — assert byte-identity against the AD-1177 text so the refactor
   cannot silently alter the shipped wording.

3. **`WorkItemAgenticExecutor.run` gains `compose_disposition: bool = True`.** When True *and*
   the config gate is on, the disposition is composed into the system prompt ahead of
   `instructions`. Default True so a **future** call site inherits it rather than having to
   remember — that is the entire lesson of this AD.

4. **The conversational call site passes `compose_disposition=False`**, with a comment stating
   why: it already carries the block through the AD-1177 hook, and a second copy would be
   duplication. Exactly one copy on every path.

5. **Config gate `AgenticToolsConfig.disposition_enabled: bool = False`**
   (`config.py:6176`, mounted on `SystemConfig` at `:7111`). Default-OFF ships byte-identical
   for every operator. Arm it in the Captain's local config as the last build step.

Reading `config.agentic_tools` inside `run` is consistent with existing behaviour — the method
already gates `browser_enabled`, `tool_search_enabled`, `oracle_query_enabled` and
`publish_finding_enabled` from that same object during tool assembly. The "reads NO config"
note in the signature applies specifically to the AD-1142 compaction parameters, whose policy
the crew executor owns; do not extend it to this.

---

## Target files

| File | Change |
|---|---|
| `src/probos/cognitive/agentic_disposition.py` | NEW. The constant + a short module docstring explaining why it is not in either caller. |
| `src/probos/cognitive/cognitive_agent.py` | `_conversational_agentic_self_description` returns the constant. Conversational call site at `:3785` passes `compose_disposition=False`. |
| `src/probos/cognitive/agentic_dispatch.py` | `run` gains `compose_disposition: bool = True`; compose into the system prompt at `:1998` when armed. |
| `src/probos/config.py` | `AgenticToolsConfig.disposition_enabled: bool = False`. |
| `docs/development/config-reference.md` | **REGENERATE — see below. Non-optional.** |
| `tests/test_ad1180_agentic_disposition.py` | NEW. |

---

## Acceptance criteria

### The config-reference trap (this WILL red the full suite if skipped)

`tests/test_config_reference_current.py::test_the_reference_matches_the_models` shells out to
`scripts/gen_config_reference.py --check`. Adding a config field without regenerating makes the
full suite fail with no other symptom:

```powershell
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
```

Stage `docs/development/config-reference.md` in the same commit.

### Tests (`tests/test_ad1180_agentic_disposition.py`)

1. **Byte-identity of the extraction.** The constant equals the exact AD-1177 text. Assert the
   full string, not a substring — this is the guard that the refactor did not reword anything.
2. **Gap-regex safety survives the move.** Import the real `is_capability_gap` from
   `probos.cognitive.decomposer`; assert False on the constant. Do not re-implement the regex.
3. **Default-OFF is byte-identical.** With `disposition_enabled` False, the `system_prompt`
   reaching the loop equals `instructions` exactly, for `compose_disposition` both True and
   False. Capture it with a recording loop stub.
4. **Armed + `compose_disposition=True` composes exactly once.** The disposition appears in the
   system prompt, and `instructions` is still fully present.
5. **Armed + `compose_disposition=False` does not compose.** The conversational path's
   guarantee — assert the system prompt equals `instructions`.
6. **No double injection on the conversational path.** Drive the real
   `_maybe_run_conversational_agentic` with the flag armed and assert the disposition appears
   **exactly once** in the system prompt that reaches the loop. Count occurrences; do not use
   `in`.
7. **Each static-instruction path composes when armed.** One test each for the crew-executor
   kwargs shape, the verifier, and delegation — asserting the disposition reaches the loop.
   These may drive `WorkItemAgenticExecutor.run` directly with the same kwargs those callers
   build; a full crew boot is not required.
8. **The default is True.** Assert via `inspect.signature` that `compose_disposition` defaults
   to True, so a new call site inherits the disposition. State the reasoning in the docstring.

Expected: **12–15 new tests.**

### Regression gates (before the full suite)

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1180_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest `
  tests/test_ad1180_agentic_disposition.py `
  tests/test_ad1177_crew_agency.py `
  tests/test_ad1070_capability_suppression.py `
  tests/test_ad1065_conversational_agentic.py `
  tests/test_bf698_thread_provenance.py `
  tests/test_ad1142_crew_child_compaction.py `
  tests/test_ad1007_capability_gate.py `
  tests/test_config_reference_current.py `
  -q -n 0
```

**Executor stubs are already `**kwargs`-tolerant** — `_FakeExecutor` / `_RaisingExecutor` /
`_EmptyExecutor` (`test_ad1065`), `_CaptureExecutor` (`test_bf698`), `_RecordingLoop`
(`test_ad1142`), `_CaptureLoop` (`test_ad1007`) all absorb new kwargs. Adding
`compose_disposition` should not break them (this is the BF-678 class; it was checked and is
clear). Verify rather than assume.

Then one full gate:

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1180_full_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q --timeout=600
```

Baseline **22,448 passed / 34 skipped** (AD-1177's gate, plus one known load-dependent flake:
`test_knowledge_store.py::TestGitIntegration::test_auto_commit_after_debounce`, tracked on
#1093 — if it fails again, re-run it `-n 0` and report, do not chase it). Reconcile exactly and
show the arithmetic.

### Arm it (Captain's standing order)

After the gate is green, set `agentic_tools.disposition_enabled: true` in the Captain's LOCAL
`config/system.yaml`, parse it through the real `SystemConfig` to prove it loads, and print a
neighbouring key to prove the adjacent construct survived. **`config/system.yaml` is
skip-worktree — edit it, NEVER stage it.** `git status` staying clean afterwards is correct.

---

## Do NOT build in this AD

- **Do not** change the disposition wording. This AD moves it and widens its reach; AD-1177
  settled the text. Any rewording is a separate decision.
- **Do not** touch `scout.py` — different executor class.
- **Do not** change the tool assembly, `_BROWSER_LOOP_ACTIONS`, or which tools any path offers.
- **Do not** touch `_conversational_agentic_will_run` or any other `_conversational_*` hook.
- **Do not** build dependency acquisition (AD-1178 / #1110) or schema generation
  (AD-1179 / #1111).
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap in the code commit.

---

## Risks to state in the report

1. **This changes crew-child behaviour by design.** Byte-identity holds only while the flag is
   off. Say so plainly rather than implying the change is inert.
2. **Prompt growth.** ~1,500 characters per agentic run across crew children, verifier
   convergence and delegation. Check whether `crew_token_budget` is affected and report the
   interaction — a budget that fails children is a hard stop, and the Captain owns that policy
   call, not the Builder.
3. If composing the disposition **ahead of** `instructions` reads worse than after it, say so
   and justify the order chosen.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
