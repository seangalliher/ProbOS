# BF-660 Builder Execution — Referent grounding Windows/precision fix

GitHub issue: #1026  
**Base:** HEAD `509e8cd7`  
**Scope:** execute only `prompts/bf-660-referent-grounding-windows-precision.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-660-referent-grounding-windows-precision.md`
- `src/probos/cognitive/referent_gate.py`
- `tests/test_ad1119_referent_gate.py`
- selector-compatible precedents in `agents/shell_command.py`, `audio/tts/piper_backend.py`, and `execution/isolation.py`

## Exact files

**Modify only:**
- `src/probos/cognitive/referent_gate.py`
- `tests/test_ad1119_referent_gate.py`

**Reference only:**
- `src/probos/__main__.py`
- `src/probos/routers/thread_fanout.py`
- `src/probos/config.py`
- `tests/test_ad1120_ground_before_collaborate.py`
- `tests/test_ad1121_confab_probe.py`

## Highest-risk instructions

1. Replace `asyncio.create_subprocess_exec` with selector-compatible `subprocess.Popen` in a worker thread.
2. `to_thread` cancellation alone does **not** stop the worker. Use a cancellation signal + shielded worker; kill and reap before re-raising `CancelledError`.
3. Git argv must remain a list: `git cat-file -e -- <token>^{object}`. Never use a command string or `shell=True`.
4. Keep `GitObjectResolver.resolve(self, token) -> bool` unchanged.
5. Keep valid identifiers (`oracle_probe`, `alpha_1`, hyphenated IDs, hex IDs). Filter ordinary grammar via a pure helper, not a sprawling regex.
6. Preserve default-OFF behavior and cue/probe logic exactly.

## Required tests

- false-positive prose (`node is`, `record shows`, `entity was`) rejected,
- valid identifier matrix preserved,
- selector-policy compatibility,
- argv/shell/cwd safety,
- timeout kill+wait,
- cancellation kill+wait+re-raise,
- nonrepo/missing-Git honest-degrade,
- existing default-OFF and AD-1120/1121 tests green.

Use strict fake process classes, not permissive `MagicMock` process APIs.

## Commands

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1119_referent_gate.py -q -n 0
    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1120_ground_before_collaborate.py tests/test_ad1121_confab_probe.py -q -n 0

Set an isolated `PROBOS_DATA_DIR` first.

## Stop conditions

Stop if:

- the child cannot be deterministically reaped on cancellation,
- a general subprocess framework is required,
- known valid identifiers would be rejected,
- or any grounding flag/default, cue, central selection, confab probe, or persistence behavior must change.

Do not edit trackers. Do not commit. Report exact tests and any deviation.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
