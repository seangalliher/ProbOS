# BF-660 — Referent grounding correctness on Windows and extraction precision

**One-line:** Make `GitObjectResolver` work under ProbOS's Windows selector event loop without orphaning children, and stop ordinary prose such as “node is” from becoming fabricated entity identifiers.

**Status:** Ready to build  
**Type:** Bug fix — **BF-660** (current highest verified BF is BF-658; assigned sequence BF-659…663; no new AD)  
GitHub issue: #1026
**HEAD verified:** `509e8cd7` (2026-07-09)  
**Dependencies:** AD-1119/1120/1121  
**Estimated tests:** 8–10 additions in the existing AD-1119 suite; AD-1120/1121 regressions unchanged

## Problem

`src/probos/cognitive/referent_gate.py` has three confirmed defects:

1. `GitObjectResolver.resolve()` uses `asyncio.create_subprocess_exec`. ProbOS installs `WindowsSelectorEventLoopPolicy` in `src/probos/__main__.py`; selector loops on Windows do not implement asyncio subprocess transports and raise `NotImplementedError`.
2. `_ENTITY_RE` accepts any two-character word after `node`, `record`, or `entity`. Live examples extract `is`, `shows`, and `was` from ordinary prose, creating false unresolved referents and false closure cues.
3. Cancellation after process spawn is not handled. The current timeout path kills/reaps, but a cancelled coroutine can leave the Git child alive.

The feature remains default-OFF through `GroundingConfig.referent_gate_enabled`; this BF fixes the opt-in path only.

## Architecture decisions

### DD-1 — Use the repository's selector-compatible `Popen`-in-thread pattern

Replace asyncio subprocess APIs with a small synchronous worker launched by `asyncio.to_thread()` (or `run_in_executor`) using `subprocess.Popen` with an argv list, `shell=False`, `cwd=str(repo_root)`, and `DEVNULL` streams.

This mirrors the proven selector-compatible patterns in:

- `agents/shell_command.py::_run_command/_run_sync`,
- `audio/tts/piper_backend.py`,
- `execution/isolation.py::SubprocessSandbox`,
- `cognitive/builder.py::_run_git` (threaded `subprocess.run`).

`subprocess.run()` alone is insufficient for the cancellation requirement because cancelling `to_thread()` does not stop the worker or child. Use `Popen` so the worker can terminate and reap explicitly.

### DD-2 — Cancellation handshake must kill and reap before re-raising

The async side creates a thread-safe cancellation signal and a separately-held worker task. Await it under `asyncio.shield()` so cancellation of `resolve()` does not cancel the worker Future. On `CancelledError`:

1. signal cancellation,
2. await the shielded worker to finish cleanup,
3. re-raise `CancelledError`.

The worker polls `proc.poll()` plus the cancellation signal at a short bounded interval, enforces the existing timeout using `time.monotonic()`, and calls `kill()` then `wait()` exactly once on cancellation or timeout. Its `finally` is a final no-orphan backstop.

Do not swallow cancellation and do not return before the child is reaped.

### DD-3 — Preserve Git argv/path injection safety

Invoke exactly an argv list equivalent to:

`["git", "cat-file", "-e", "--", f"{token}^{{object}}"]`

The `--` terminates options; `git cat-file -e -- HEAD^{object}` is valid at live HEAD, and a token beginning with `--` is treated as an object name rather than an option. Keep `shell=False`; never interpolate into a command string. Keep `cwd` a direct path argument.

### DD-4 — Identifier syntax plus a focused grammar stop-set

Keep all currently valid identifier shapes:

- `node oracle_probe`
- `node id oracle_probe`
- `record alpha_1`
- hyphenated identifiers such as `record alpha-1`
- 7–40 character hex IDs (handled independently by `_HEX_RE`)

Retain the current ASCII token syntax `[A-Za-z0-9_-]{2,64}`, but require a machine-like identifier signal **or** reject a curated grammar/closure-word stop-set:

- machine-like signal: contains a digit, underscore, or hyphen;
- plain alphabetic tokens remain allowed when they are not common copular/reporting verbs or determiners.

At minimum reject case-insensitively: `is`, `are`, `was`, `were`, `be`, `been`, `being`, `shows`, `showed`, `showing`, `has`, `have`, `had`, `does`, `did`, `will`, `would`, `can`, `could`, `should`, `the`, `this`, `that`, `these`, `those`, `a`, `an`.

Implement the precision filter in one pure helper called by `extract_referents()` after regex matching; do not grow a brittle negative-lookahead regex. Preserve first-seen ordering, de-duplication, code-span stripping, and `_MAX_REFERENTS`.

### DD-5 — Do not collapse Git-unavailable and object-missing semantics

Both still return `False` to the gate, but logging remains differentiated:

- missing Git/non-repo/start failure: contextual DEBUG,
- timeout: contextual WARNING,
- cancellation: cleanup then propagate (no “unresolved” conversion),
- nonzero Git return for a missing object: `False` without treating it as an operational exception.

## Implementation

### Section 1 — Replace `GitObjectResolver` subprocess mechanics

Modify `src/probos/cognitive/referent_gate.py`:

- Import `subprocess`, `threading`, and `time` as needed; remove the direct `create_subprocess_exec` dependency.
- Add one private synchronous helper owned by `GitObjectResolver` or the module. It returns a small status/return code, not a process object.
- Use `Popen` with the exact argv contract from DD-3.
- Enforce `self._timeout` in the worker without relying on async `wait_for`.
- On timeout/cancel, kill and reap. Catch `FileNotFoundError`, `NotADirectoryError`, and `OSError` with existing honest-degrade behavior.
- `resolve()` must remain `async def resolve(self, token: str) -> bool`.
- Explicitly catch `asyncio.CancelledError`, perform the DD-2 handshake, and re-raise.

Do not use `CREATE_NEW_PROCESS_GROUP`; Git `cat-file -e` has no child tree and a direct `kill()` is sufficient. Do not introduce a general subprocess abstraction in this BF.

### Section 2 — Add precise entity-token filtering

In the same module:

- Keep `_ENTITY_RE` responsible only for locating the prefix and token.
- Add a pure `_is_entity_identifier(token: str) -> bool` (private, fully typed).
- Apply it before appending an entity match.
- Document why machine-like tokens pass and ordinary grammar tokens fail.
- Keep `_HEX_RE` independent, so valid hex identifiers still resolve even when they also appear after `entity`.

### Section 3 — Extend the real AD-1119 test suite

Modify `tests/test_ad1119_referent_gate.py`.

Extraction tests:

1. `test_extract_rejects_ordinary_verb_after_entity_prefix` covering exactly `node is`, `record shows`, `entity was` and representative inflections.
2. `test_extract_preserves_known_valid_entity_identifiers` covering `node oracle_probe`, `node id oracle_probe`, `record alpha_1`, a hyphenated ID, and a valid hex ID.
3. Keep code-span, decimal, ordering, dedupe, and cap tests green.

Windows/subprocess tests:

4. `test_git_resolver_uses_threaded_popen_not_asyncio_subprocess` — monkeypatch `asyncio.create_subprocess_exec` to raise `NotImplementedError`; a real temporary Git repo still resolves full and abbreviated SHA.
5. `test_git_resolver_argv_is_shell_free_and_option_terminated` — patch `subprocess.Popen` with a real strict fake recording args; assert list argv, `--` before object expression, `cwd`, `DEVNULL`, and no `shell=True`.
6. `test_git_resolver_timeout_kills_and_reaps` — fake process never exits until killed; assert `kill()` and `wait()` occurred and result is false.
7. `test_git_resolver_cancellation_kills_reaps_and_reraises` — deterministic blocking fake; cancel after spawn; assert `CancelledError`, kill, wait, and no worker/child leak.
8. `test_git_resolver_nonrepo_and_missing_git_degrade_false` — preserve existing behavior/log level.
9. Existing real-Git full-SHA/abbreviation test remains.
10. Existing default-OFF fanout test remains and must still prove no resolver/Git work.

A fake process must model the live `Popen` methods used by the worker (`poll`, `wait`, `kill`, `returncode`) rather than a permissive `MagicMock`.

## Do Not Build

- Do **not** enable referent grounding by default or change `GroundingConfig`.
- Do **not** modify central-referent selection, cue wording, confab probing, notifications, or evidence persistence.
- Do **not** add fuzzy/NER/LLM extraction.
- Do **not** reject all plain alphabetic identifiers; `node oracle`-style names remain legal unless they are in the grammar stop-set.
- Do **not** use shell command strings, `shell=True`, or path concatenation.
- Do **not** add a global subprocess service or modify unrelated asyncio subprocess users.
- Do **not** edit `PROGRESS.md` or `DECISIONS.md`.

## Files

**Modify:**
- `src/probos/cognitive/referent_gate.py`
- `tests/test_ad1119_referent_gate.py`

**Reference only:**
- `src/probos/__main__.py`
- `src/probos/agents/shell_command.py`
- `src/probos/audio/tts/piper_backend.py`
- `src/probos/execution/isolation.py`
- `src/probos/cognitive/builder.py`
- `src/probos/routers/thread_fanout.py`
- `src/probos/config.py`
- `tests/test_ad1120_ground_before_collaborate.py`
- `tests/test_ad1121_confab_probe.py`

## Test commands

Focused:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1119_referent_gate.py -q -n 0

Blast radius:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1120_ground_before_collaborate.py tests/test_ad1121_confab_probe.py -q -n 0

Run on Windows with the repository venv and an isolated `PROBOS_DATA_DIR`.

## Acceptance criteria

1. `GitObjectResolver.resolve()` works under `WindowsSelectorEventLoopPolicy`; it does not call asyncio subprocess APIs.
2. Git invocation is an argv list with `shell=False`, option terminator `--`, explicit `cwd`, and no token/path interpolation into a shell string.
3. Timeout and cancellation both kill and reap the child; cancellation is re-raised only after cleanup.
4. `node is`, `record shows`, and `entity was` produce no referents.
5. `node oracle_probe`, `node id oracle_probe`, `record alpha_1`, hyphenated IDs, and hex IDs remain extractable.
6. Default-OFF fanout remains byte-identical and starts no subprocess.
7. AD-1119/1120/1121 focused and blast-radius suites pass.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop conditions

Stop and return to the Architect if:

- cancellation cannot be proven to reap the child deterministically,
- the implementation needs a shared/global subprocess manager,
- valid known identifiers must be narrowed beyond DD-4,
- or any behavioral grounding/config flag would change.

## Verified Against Codebase (2026-07-09, HEAD 509e8cd7)

- `src/probos/__main__.py` installs `asyncio.WindowsSelectorEventLoopPolicy()` on Windows.
- `src/probos/cognitive/referent_gate.py` currently calls `asyncio.create_subprocess_exec("git", "cat-file", "-e", f"{token}^{object}")` and handles timeout but not cancellation.
- `src/probos/agents/shell_command.py` explicitly documents `Popen` in a thread executor for selector-loop compatibility.
- `src/probos/audio/tts/piper_backend.py` cites the same Windows-selector reason and kills/reaps on timeout.
- `src/probos/cognitive/builder.py::_run_git` uses threaded `subprocess.run` for Windows compatibility.
- `tests/test_ad1119_referent_gate.py` has a real temporary-Git helper and full/abbreviated SHA assertions.
- Empirical extraction at HEAD: `node is → is`, `record shows → shows`, `entity was → was`; `node oracle_probe` and `record alpha_1` remain valid.
- Live Git probe confirmed `git cat-file -e -- HEAD^{object}` succeeds and an option-shaped token after `--` is treated as an invalid object, not an option.
