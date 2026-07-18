# BF-673 Builder Execution - Correct group trigger provenance

**Verdict:** APPROVED FOR BUILDER HANDOFF
**Binding specification:** `prompts/bf-673-group-trigger-provenance.md`
**Exact base:** `cbf008ac9e5ae87ac7654e358420fce63b2f8246`
**Exact base commit:** `AD-722b-5a: wire federation avatar telemetry relay (closes #659)`
**Scope:** Execute BF-673 only. No AD, config, API, UI, dependency, store, orchestration, GitHub mutation, or push.
**Numbering:** current ceilings are AD-1123 / BF-672; build BF-673 only.

## Pre-flight

Before implementation, test edits, staging, commit, or any other mutation:

1. Read `.github/copilot-instructions.md`, `prompts/_TEMPLATE.md`, `prompts/review-criteria.md`, this execution prompt, and the complete binding prompt.
2. `git rev-parse HEAD` must equal `cbf008ac9e5ae87ac7654e358420fce63b2f8246`.
3. `git rev-parse origin/main` must equal the same SHA.
4. `git status --short` may contain only:
   - `?? prompts/bf-673-group-trigger-provenance.md`
   - `?? prompts/bf-673-group-trigger-provenance-execution.md`
5. There must be no staged path, tracked modification, deletion, or other untracked path.
6. Recompute and require these exact hashes:
   - `src/probos/routers/thread_fanout.py` -> `63baf267b488bac302cf5d6a9a573cfde222758da5790cbea3e089fa69ad7e67`
   - `src/probos/cognitive/cognitive_agent.py` -> `dbb63f7d18d558257eacee72db010c170852caa9ee0936d7ead2fb6f7c3d8cae`
   - `tests/test_ad970_agent_kickoff.py` -> `8942eb6d03b1757bc66dda56c9fd0bad38f48c667d9d899e0dddc863d369565c`
7. Verify PROGRESS/DECISIONS/roadmap still identify AD-1123 and BF-672 as the ceilings and no BF-673 has landed.
8. Do not create/comment/label/edit/close any GitHub issue. The orchestrator owns issue filing.

If any pre-flight check differs, stop. Do not rebase, merge, cherry-pick, reset, clean, stash, restore, checkout, regenerate, or move the prompt to another base.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/bf-673-group-trigger-provenance.md` - binding
- `src/probos/proactive.py` around `_kickoff_group_chat` - reference only
- `src/probos/routers/thread_fanout.py` complete `_fan_one_round` and `group_chat_fanout`
- `src/probos/cognitive/cognitive_agent.py` complete direct-message `_build_user_message` branch
- `tests/test_ad970_agent_kickoff.py`
- every test file in the three exact gates

Do not implement from this execution summary alone. The binding prompt's DD-1 through DD-5, acceptance criteria, scope fences, hashes, and hard stops are authoritative.

## Exact allowlist

### Builder may modify production

- `src/probos/routers/thread_fanout.py`
- `src/probos/cognitive/cognitive_agent.py`

### Builder may modify tests

- `tests/test_ad970_agent_kickoff.py`

### Architect documents already present; retain byte-for-byte

- `prompts/bf-673-group-trigger-provenance.md`
- `prompts/bf-673-group-trigger-provenance-execution.md`

### Conditional closeout after green gates and review

- `PROGRESS.md`

No other file is authorized. A needed edit outside this list is a hard stop.

## Red-first sequence

### Step 1 - Add failing tests only

Edit only `tests/test_ad970_agent_kickoff.py`:

1. import `CognitiveAgent` from `probos.cognitive.cognitive_agent`;
2. in `test_kickoff_fires_when_enabled`, keep the `intents` return from `_build_env` and assert the one recipient intent has exact `params["trigger_speaker"] == "Scout"`;
3. in `test_no_opener_id_fans_to_all`, retain `intents` and assert every round-zero intent has exact `trigger_speaker == "Captain"`;
4. add a pure test for group agent formatting (`Scout says: Status?`);
5. add a pure test for empty group speaker formatting (`Room conversation:\nScout: first\nBones: second`, no `Captain says:`);
6. add a pure test proving a 1:1 ignores `trigger_speaker="Scout"` and remains exact `Captain says: Status?`;
7. add an end-to-end kickoff with the opener callsign absent from the callsign
   map and assert exact stable-id fallback `scout1`;
8. add a recording episodic fake plus an enabled
   `memory.group_episode_enrichment_enabled` case and assert the kickoff episode
   has `anchors.trigger_agent == "Scout"` and a `[group chat] Scout:` user-input
   prefix.

Run:

```powershell
$gateDir = Join-Path $env:TEMP ('probos_bf673_red_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad970_agent_kickoff.py -p no:cacheprovider -n 0 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected RED: the base has no `trigger_speaker` param, no formatter, and writes
`Captain` into the enriched kickoff episode. Record exact failing test node
ids/reasons in the build report. If the tests unexpectedly pass or fail for
another reason, stop and return to the Architect.

### Step 2 - Implement fan-out provenance

In `src/probos/routers/thread_fanout.py` only:

1. add `"trigger_speaker": trigger_speaker` to `_send_one`'s server-built group params;
2. before the round-zero `_fan_one_round` call, derive one local label from existing state:
   - `"Captain"` without `opener_id`;
   - `_roster_callsigns.get(opener_id) or opener_id` with `opener_id`;
3. replace only the round-zero hardcoded `trigger_speaker="Captain"` argument with that local value.

Keep cascade calls at `trigger_speaker=""`. Do not add another callsign lookup, schema, config, request field, metadata key, or message rewrite.

Rerun the red test module. Param assertions should now pass; formatter tests should remain red until Step 3.

### Step 3 - Implement prompt-boundary formatter

In `src/probos/cognitive/cognitive_agent.py` only:

1. add private static `_format_direct_message_trigger(params: dict[str, Any]) -> str` with the exact DD-2 table;
2. replace only the hardcoded direct-message `Captain says:` emit payload with a call to that helper;
3. keep attention-bid source `captain_message` and ordering unchanged.

Rerun the red module. All tests must pass.

### Step 4 - Exact gates

Run all three exact commands below. Fix only BF-673 failures inside the allowlist.

#### Gate 1 - kickoff and group prompt provenance

Pinned base: **25 passed**. Expected post-build: **30 passed**, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_bf673_gate1_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad970_agent_kickoff.py tests/test_ad967_room_roster.py tests/test_ad975_turn_taking_self_knowledge.py -p no:cacheprovider -n 0 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

#### Gate 2 - fan-out, cascade, and episode provenance

Pinned base: **48 passed**. Expected post-build: **48 passed**, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_bf673_gate2_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad914_group_chat_fanout.py tests/test_ad935_group_reactivity.py tests/test_ad933a_group_episode.py tests/test_ad986a_987_group_memory_enrichment.py -p no:cacheprovider -n 0 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

#### Gate 3 - 1:1 direct-message parity

Pinned base: **99 passed**. Expected post-build: **99 passed**, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_bf673_gate3_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1028_context_assembler.py tests/test_ad1029_attention_faculty.py tests/test_cognitive_agent.py -p no:cacheprovider -n 0 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not substitute a broad/full suite, `-n auto`, live data, or network/model calls.

## Highest-risk invariants

1. 1:1 remains exact `Captain says:`.
2. Group speaker label is server-owned.
3. Agent kickoff uses opener callsign, then stable id fallback.
4. Cascade uses `Room conversation`, never false Captain attribution.
5. Existing `_fan_one_round(trigger_speaker)` remains the single carrier.
6. AD-986a receives the same truthful label automatically; do not add a second episode field.
7. No transcript/API/UI/config/store/event/trust/artifact/Todo behavior changes.
8. No new async task or lifecycle work.
9. Prompts remain byte-for-byte.
10. No GitHub mutation or push.

## Three-pass Builder review

### Pass 1 - Behavior/spec

- Map every DD and acceptance item to exact code/tests.
- Trace Captain round, agent kickoff with callsign, opener-id fallback, and cascade.
- Prove 1:1 ignores the new param.

### Pass 2 - Verify-first/code

- Re-grep all `_fan_one_round` callers and all `Captain says:` assertions.
- Confirm params are built server-side and no API/request model accepts `trigger_speaker`.
- Inspect episode enrichment and attention-bid ordering line-by-line.

### Pass 3 - Scope/safety

- Verify exact allowlist and no deletions/bulk formatting.
- Confirm no config/YAML/API/UI/store/event/dependency/tracker drift beyond conditional `PROGRESS.md`.
- Recompute prompt hashes before staging; they must match their post-Architect values.

## Closeout

After exact gates and three-pass review:

1. update only `PROGRESS.md` as specified by the binding prompt;
2. run editor diagnostics on both changed Python files and the test file;
3. run whitespace/deletion/scope audits;
4. stage explicit allowlisted paths only;
5. commit exactly `BF-673: correct group trigger provenance`;
6. do not push;
7. do not create, edit, close, label, comment on, or assign any GitHub issue;
8. return the local commit SHA, exact test counts/durations, changed paths, and three-pass review result to the Architect/orchestrator.

## Audit commands

Before staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D cbf008ac9e5ae87ac7654e358420fce63b2f8246 --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-673-group-trigger-provenance.md
git diff --no-index --check -- NUL prompts/bf-673-group-trigger-provenance-execution.md
```

For each no-index command, exit code 1 is expected because a non-empty file differs from NUL; any emitted whitespace diagnostic is a failure.

After staging:

```powershell
git diff --cached --check
git diff --cached --name-only
git diff --cached --name-only --diff-filter=D
git diff --cached --stat
git diff --cached --numstat
```

Do not use `git add -A`. Stage exact allowlisted paths only.

## Hard stops

Stop for Architect review on any base/hash/status mismatch, any needed file outside the allowlist, any changed 1:1 golden, any client-authored provenance requirement, any new schema/config/API/event/store need, any unexplained serial test failure, or any request to push/mutate GitHub.
