# Execution Instructions: AD-262 + AD-263

## HIGH-RISK CONSTRAINTS — READ FIRST

1. **Do NOT modify `decomposer.py`** — the legacy system prompt is a backward-compat fallback. Changing it risks breaking tests that use standalone `IntentDecomposer` without `PromptBuilder`.
2. **Do NOT modify any file outside the 5 listed** — `shell_command.py`, `prompt_builder.py`, `test_prompt_builder.py`, `test_expansion_agents.py`, and `PROGRESS.md`. Nothing else.
3. **Do NOT add new intents, agents, or capabilities.** This is a prompt patch, not a feature.
4. **Do NOT change `_run_sync()` subprocess logic** — only add the `_rewrite_python_interpreter()` call in `_run_command()`.
5. **After EVERY edit, run the test suite**: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`. Report the count. Do not proceed if tests fail.

## Execution order

1. Edit `src/probos/agents/shell_command.py`:
   - Reword the `IntentDescriptor.description` on line 45
   - Add `_BARE_PYTHON_RE` regex near line 21 (after `_PS_WRAPPER_RE`)
   - Add `_rewrite_python_interpreter()` static method after `_strip_ps_wrapper()` (after line 157)
   - Add the call to `_rewrite_python_interpreter()` in `_run_command()` — AFTER `_strip_ps_wrapper()`, OUTSIDE the `if sys.platform == "win32"` block (applies to all platforms)
   - **Run tests.** Existing tests should pass unchanged.

2. Edit `src/probos/cognitive/prompt_builder.py`:
   - Add the QR code tuple to `_GAP_EXAMPLES` list (after the Alan Turing entry)
   - In `_build_rules()`, change the comment on line 273 from "Encourage using run_command" to "Constrain run_command"
   - Add the anti-scripting rule after the existing two run_command rules (inside the `if "run_command" in intent_names:` block)
   - **Run tests.** Existing tests should pass unchanged — the tests check for rule presence, not exact wording.

3. Add new tests to `tests/test_prompt_builder.py`:
   - `test_run_command_description_no_blank_check` in `TestPromptBuilder`
   - `test_anti_scripting_rule_present` in `TestPromptBuilder`
   - `test_qr_gap_example_present` in `TestCapabilityGapExamples`
   - `test_qr_gap_suppressed_when_qr_intent_exists` in `TestCapabilityGapExamples`
   - **Run tests.** All 4 new tests should pass.

4. Add new tests to `tests/test_expansion_agents.py`:
   - `test_rewrite_bare_python`, `test_rewrite_python3`, `test_no_rewrite_other_commands`, `test_no_rewrite_full_path_python` in `TestShellCommandAgent`
   - **Run tests.** All new tests should pass.

5. **Final full suite run.** Report total count. Expected: baseline + 8 new tests.

6. **Update `PROGRESS.md`:**
   - Update the status line (line 3) with the new test count: `## Current Status: Phase 23 — HXI MVP "See Your AI Thinking" (NNNN/NNNN tests + 11 skipped)` where NNNN is the final passing count.
   - Add a new section after the last phase entry (after the Phase 23 section, before `## Active Roadmap`). Format:

   ```
   ### AD-262 + AD-263: Close `run_command` Escape Hatch + Fix Python Interpreter Path

   **Problem:** Sonnet routes requests like "generate a QR code" to `run_command` with `python -c "import qrcode; ..."` instead of flagging a capability gap. The `run_command` IntentDescriptor says "anything a shell can do" — a blank check. Additionally, when the LLM does generate `python -c ...`, the bare `python` isn't on PATH (venv's interpreter not exposed).

   | AD | Decision |
   |----|----------|
   | AD-262 | Prompt hardening: reworded `run_command` descriptor (removed "anything a shell can do"), added anti-scripting rule (explicit ban on `python -c`/`node -e` workarounds), added QR-code capability gap example to `_GAP_EXAMPLES` |
   | AD-263 | `_rewrite_python_interpreter()` — detects bare `python`/`python3` at command start, replaces with `sys.executable`. Same preprocessing pattern as `_strip_ps_wrapper()`. Applied on all platforms |

   **Files changed:**

   | File | Change |
   |------|--------|
   | `src/probos/agents/shell_command.py` | Reworded IntentDescriptor description, added `_BARE_PYTHON_RE` + `_rewrite_python_interpreter()`, wired in `_run_command()` |
   | `src/probos/cognitive/prompt_builder.py` | Added anti-scripting rule to `_build_rules()`, added QR code entry to `_GAP_EXAMPLES` |
   | `tests/test_prompt_builder.py` | 4 new tests: descriptor wording, anti-scripting rule, QR gap present, QR gap suppressed |
   | `tests/test_expansion_agents.py` | 4 new tests: python rewrite, python3 rewrite, passthrough, full-path passthrough |

   NNNN/NNNN tests passing (+ 11 skipped). 8 new tests.
   ```

   Replace NNNN with the actual final test count in both the status line and the section footer.
