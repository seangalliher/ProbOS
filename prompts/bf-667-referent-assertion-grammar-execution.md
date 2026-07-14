# BF-667 Builder Execution — Referent assertion grammar

**Verdict:** APPROVED FOR BUILDER
**GitHub issue:** #1033 — https://github.com/seangalliher/ProbOS/issues/1033
**Exact base:** `5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2`
**Scope:** Execute only `prompts/bf-667-referent-assertion-grammar.md`. BF-667 is a deterministic referent-precision bug fix; no AD, no `DECISIONS.md`, no UI, no config/dependency change.
**License disposition:** none.

## Pre-flight — exact base and authorized initial tree

Before implementation or test edits:

1. `git rev-parse HEAD` must equal exactly `5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2`.
2. `git status --short` may show **only** these two Architect-authored untracked files:
   - `?? prompts/bf-667-referent-assertion-grammar.md`
   - `?? prompts/bf-667-referent-assertion-grammar-execution.md`
3. There must be no staged file, tracked modification, or other untracked file.
4. BF-666 CI for this SHA was read-only verified successful during drafting. If an orchestrator reports CI failure, the remote base moves, or local HEAD moves, hard-stop for Architect re-verification. Do not attempt a rebase/merge/cherry-pick/reset.
5. Do not stash, restore, checkout, reset, clean, stage, commit, push, or mutate GitHub during pre-flight.
6. Any base/tree difference is a hard stop.

Do not stage, commit, push, or mutate GitHub at any later step unless the orchestrator explicitly directs that exact operation after Architect review.

Current numbering at this exact base is AD-1121 / BF-666. Use issue-reserved BF-667 only. Do not mint an AD or edit `DECISIONS.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/bf-667-referent-assertion-grammar.md` — **binding; read fully**
- `src/probos/cognitive/referent_gate.py`
- `src/probos/routers/thread_fanout.py`
- `tests/test_ad1119_referent_gate.py`
- `tests/test_ad1120_ground_before_collaborate.py`
- `tests/test_ad1121_confab_probe.py`
- `tests/test_ad970_agent_kickoff.py`
- `prompts/ad-1119-referent-grounding-gate.md`
- `prompts/ad-1120-ground-before-collaborate.md`
- `prompts/ad-1121-confab-divergence-probe.md`
- `prompts/bf-660-referent-grounding-windows-precision.md`
- `prompts/bf-660-referent-grounding-windows-precision-execution.md`
- `src/probos/cognitive/decomposer.py` capability-gap regex
- `src/probos/config.py` `GroundingConfig` (reference only)
- `config/system.yaml` grounding flags (reference only)
- `src/probos/substrate/registry.py`, `src/probos/crew_profile.py`, `src/probos/ward_room/service.py` resolver APIs (reference only)
- `src/probos/proactive.py` AD-970 kickoff caller (reference only)
- `src/probos/routers/threads.py` Captain caller (reference only)

Do not implement from this execution summary alone. The main prompt’s DD-1 through DD-8, required tests, acceptance criteria, do-not-build list, and hard stops are binding.

---

## Exact allowlist

### Builder may modify production

- `src/probos/cognitive/referent_gate.py`
- `src/probos/routers/thread_fanout.py`

### Builder may modify existing tests

- `tests/test_ad1119_referent_gate.py`
- `tests/test_ad1120_ground_before_collaborate.py`
- `tests/test_ad1121_confab_probe.py`
- `tests/test_ad970_agent_kickoff.py`

### Architect documents already present; retain unchanged during build

- `prompts/bf-667-referent-assertion-grammar.md`
- `prompts/bf-667-referent-assertion-grammar-execution.md`

### Conditional closeout only, and only if the orchestrator explicitly directs it

- `PROGRESS.md`

No new source/test file is authorized. No other source, test, config, standing-order, workflow, UI, tracker, roadmap, decision, era, archive, dependency, data/log, or issue file is authorized.

---

## Highest-risk invariants — redundant standing order

1. **Classify at source.** Assertion strength comes from syntax/machine shape in `extract_referents()`, not a downstream noun filter.
2. **No noun blacklist.** Do not add conceptual nouns to BF-660’s stop-set or any new set.
3. **Backward-compatible frozen fields.** Append `Referent.claim_confidence: Literal["strong","implicit"] = "strong"` and `GroundingVerdict.ambiguous: tuple[str,...] = ()` after current required fields.
4. **Two result labels only.** `results` remains `RESOLVED|UNRESOLVED`. Ambiguous means resolver-unconfirmed but non-actionable; it is not a third resolver result.
5. **Resolution still runs.** Bare alpha names are implicit, not discarded. Every implicit token reaches the existing resolver chain once; a real `node oracle` resolves.
6. **Strong unknowns remain actionable.** Hex, digit/underscore/hyphen, explicit `node id`, matching ASCII single/double quotes, and genuine service forms keep cues/probes when unconfirmed.
7. **Backticks remain code.** Inline/fenced backtick spans stay stripped. Never reinterpret backticks as quoted identifiers.
8. **Quotes are single-token ASCII identifiers.** No multiword/curly/mismatched/unclosed quote support.
9. **BF-660 grammar wins.** `node id is/was/shows` produces no referent. Do not regress Windows Git process/cancellation behavior.
10. **Reserve incomplete explicit syntax.** ``node id `oracle_probe` `` and `node id` cannot fall back to token `id`.
11. **Service grammar is not broadened.** Keep exact service keywords/token syntax. Reject only grammar-role/determiner/locator captures such as `The`/`Node` and captured names that repeat an existing service-role keyword (for example `Service node`); preserve `Oracle membership` and `oracle_service telemetry`.
12. **Exact casing and token keys.** No casefold normalization of returned tokens, dedupe keys, or resolver calls.
13. **Promotion is in place.** Later strong evidence upgrades an earlier implicit duplicate without moving it. Later implicit cannot downgrade.
14. **Cap semantics include promotion.** Admit at most 20 unique tokens, but still permit later promotion of one already admitted.
15. **No ambiguous side effect.** Ambiguous-only verdict: no `unresolved`, cue, warning, central token, probe task, LLM request, evidence, notification, or injected param.
16. **Remove only duplicated router stopwords.** Delete `_GROUNDING_STOPWORDS`; retain `_GROUNDING_INJECT_KINDS` and the hex Git-availability policy.
17. **One central computation.** Zero selector calls when B2+probe are off; at most one when either is on; reuse for warning/cue/probe.
18. **Truthful warning.** Strong unresolved warning includes central/B2/probe state and never contains `no behavioral change`.
19. **Default-OFF first line stays first.** Gate false means no extraction/resolver/Git/warning/selector/task work.
20. **Local enablement stays enabled.** Do not edit `config/system.yaml` or Pydantic flags.
21. **Resolver authority unchanged.** No new resolver, reorder, fuzzy lookup, kind bypass, signature change, or Git change.
22. **Cue/probe authority unchanged.** No cue wording, capability-gap regex, probe classifier, sample, nonce, task lifecycle, notification, or evidence change.
23. **Shared origin seam remains.** Captain and AD-970 agent-created seeds both use the corrected gate; never add origin restriction.
24. **No broad fan-out refactor.** Two production files only; no second seam, task, event, intent, or protocol.
25. **No broad tests.** Serial focused/blast commands only; no full suite, xdist, network, live LLM, or live data.

---

## Ordered checklist

### Step 1 — Verify base, tree, symbols, and current failures

- Confirm exact SHA and two-doc-only status.
- Grep all `extract_referents`, `Referent(`, `GroundingVerdict(`, `_observe_referent_grounding`, and `_select_central_referent` callers.
- Reconfirm current `node identity distribution -> identity` extraction and current false `no behavioral change` log literal.
- Confirm both target test additions fail before implementation without changing expectations to current behavior.
- Do not query or mutate live runtime data and do not run broad baseline tests.

### Step 2 — Append metadata safely

- Add `Literal` typing import.
- Append defaulted fields in legal frozen-dataclass order.
- Update data-contract docstrings.
- Add old-constructor/default/frozen assertions.

Hard gate: no existing constructor call requires edits merely to satisfy the new defaults.

### Step 3 — Encode assertion grammar

- Keep code-span stripping and `_HEX_RE`.
- Split quoted / explicit `node id` / bare locator recognition.
- Classify bare machine-shaped as strong; bare alphabetic non-grammar as implicit; grammar as absent.
- Reserve explicit-marker fallthrough.
- Filter impossible service names by existing grammar roles only.

Hard gate: no conceptual noun appears in a new/expanded stop-set.

### Step 4 — Preserve ordering, dedupe, promotion, and cap

- Use deterministic source position + syntax priority.
- Preserve hex interpretation at same token position.
- Exact-token first-seen order.
- Later strong replaces metadata in place.
- Continue scanning admitted duplicates after unique cap.

Hard gate: output remains at most 20 and deterministic.

### Step 5 — Separate resolver fact from actionability

- Call the existing resolver chain exactly once per deduped referent.
- Resolved: unchanged.
- Strong unconfirmed: existing unresolved+cue path.
- Implicit unconfirmed: `results=UNRESOLVED`, `ambiguous`, no actionable fields.
- Keep honest-degrade and cancellation semantics.

### Step 6 — Simplify central selection and warning disposition

- Remove `_GROUNDING_STOPWORDS` only.
- Compute central once before warnings only if B2/probe is enabled.
- Warn only for `verdict.unresolved` with token/cue/central/B2/probe fields.
- Remove false literal.
- Reuse central for existing probe and cue paths.

Hard gate: no second extraction beyond the selector’s existing pure kind recovery and no second resolver pass.

### Step 7 — Extend only the four existing test suites

Implement every required case in the main prompt:

- conceptual matrix;
- real identifiers / explicit `id` / quotes / code spans;
- case/punctuation;
- BF-660 grammar continuation;
- service preservation/collision suppression;
- promotion/order/dedupe/cap;
- implicit resolve vs ambiguity;
- strong cue + capability-gap safety;
- central cue/probe no-false-action;
- truthful warning;
- default-OFF;
- fabricated `e77acec7` preservation;
- AD-970 agent-created conceptual kickoff.

Use strict fixtures/stubs; no MagicMock-generated substrate contracts, live LLM, network, live DB, or sleeps.

### Step 8 — Focused then blast gates

Run the exact commands below. Fix only BF-667 regressions inside the allowlist. A reproducible need outside it is a hard stop.

### Step 9 — Three-pass Builder self-review

**Pass 1 — Behavior/spec:** map every DD/test/acceptance item; verify ambiguity has no side effect and strong paths remain.

**Pass 2 — Verify-first/code:** re-grep every changed seam/signature/caller; inspect dataclass ordering, regex overlap, promotion, cap, resolver count, central count, and warning fields.

**Pass 3 — Scope/safety/license:** verify exact allowlist, no config/flags/resolver/probe/UI/dependency/tracker drift, no noun blacklist, no broad refactor. License remains none.

### Step 10 — Whitespace, status, and deletion audit

Without staging:

- `git status --short` must contain only the two prompt docs plus authorized production/tests (and `PROGRESS.md` only if closeout was explicitly authorized).
- `git diff --check` for tracked edits.
- Direct no-index whitespace checks for each untracked Architect doc:
  - `git diff --no-index --check -- NUL prompts/bf-667-referent-assertion-grammar.md`
  - `git diff --no-index --check -- NUL prompts/bf-667-referent-assertion-grammar-execution.md`
  - Exit code `1` is expected for content difference; any emitted whitespace diagnostic is a failure.
- `git diff --name-only --diff-filter=D 5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2 --` must be empty.
- `git diff --stat` and `git diff --numstat`; any unrelated bulk reformat/deletion is a hard stop.
- Inspect exact source diff for result-label drift, backtick extraction, noun lists, duplicate central calls, resolver/probe edits, or false warning text.

### Step 11 — Conditional closeout/commit only when directed

Only after green gates, Architect approval, and an explicit orchestrator instruction:

1. update `PROGRESS.md` only with concise BF-667 closeout, exact counts/skips, #1033, and no new AD;
2. keep both prompt documents unchanged and include them;
3. do not edit `DECISIONS.md`, roadmap, era files, issue metadata, or GitHub;
4. stage only allowlisted paths;
5. rerun staged deletion/name/whitespace audits;
6. commit exactly:

`BF-667: distinguish asserted referent identifiers (closes #1033)`

Do not push or mutate GitHub unless the orchestrator separately directs it.

---

## Exact test gates

Run from `D:\ProbOS`.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf667_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1119_referent_gate.py tests/test_ad1120_ground_before_collaborate.py tests/test_ad1121_confab_probe.py tests/test_ad970_agent_kickoff.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf667_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad914_group_chat_fanout.py tests/test_ad915_turn_taking_facilitator.py tests/test_ad935_group_reactivity.py tests/test_ad454_evidence_collector.py tests/test_bf663_confab_probe_shutdown.py tests/test_config.py tests/test_ad1119_referent_gate.py tests/test_ad1120_ground_before_collaborate.py tests/test_ad1121_confab_probe.py tests/test_ad970_agent_kickoff.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Report exact passed/failed/skipped counts and duration. Do not substitute `-n auto`, parallel xdist, or the full suite.

---

## Deletion and scope audit commands

Run before any authorized staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2 --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-667-referent-assertion-grammar.md
git diff --no-index --check -- NUL prompts/bf-667-referent-assertion-grammar-execution.md
```

Allowed final paths before conditional closeout:

```text
prompts/bf-667-referent-assertion-grammar.md
prompts/bf-667-referent-assertion-grammar-execution.md
src/probos/cognitive/referent_gate.py
src/probos/routers/thread_fanout.py
tests/test_ad1119_referent_gate.py
tests/test_ad1120_ground_before_collaborate.py
tests/test_ad1121_confab_probe.py
tests/test_ad970_agent_kickoff.py
```

`PROGRESS.md` is allowed only after explicit closeout direction. Any other path is a hard stop.

---

## Stop conditions

Stop and report to the Architect if:

- exact base/tree pre-flight fails or BF-666 CI/base is reported failed/moved;
- any needed file is outside the allowlist;
- a third result status or resolver/protocol/Git change appears necessary;
- a noun blacklist appears necessary;
- quotes cannot be supported without extracting backtick/fenced code;
- service behavior requires vocabulary/resolver broadening;
- casefold normalization appears necessary;
- central selection would run more than once or resolution more than once;
- ambiguous-only input causes any cue/log/task/LLM/evidence/notification;
- default-OFF or AD-970 shared-seam behavior weakens;
- a cue becomes capability-gap-positive;
- BF-660 Windows/cancellation tests, BF-663 lifecycle tests, or existing AD-1120/1121 behavior regresses;
- tests need live data/network/LLM/sleeps/full-suite/xdist;
- any deletion, bulk reformat, unrelated edit, staged content, Git operation, or GitHub mutation appears.

Do not guess around a hard stop.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
