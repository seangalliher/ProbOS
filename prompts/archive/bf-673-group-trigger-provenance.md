# BF-673 - Correct group-chat trigger speaker provenance

**Verdict:** APPROVED FOR BUILDER HANDOFF
**One-line:** Preserve 1:1 Captain wording, but make an agent-created room kickoff identify the real opener and make unlabeled cascade context identify the room rather than falsely attributing either to the Captain.

**Status:** Build-ready on exact clean base
**Type:** Bug fix - **BF-673**; no new AD and no `DECISIONS.md` or roadmap entry
**GitHub issue:** pending orchestrator filing; do not mutate GitHub from this prompt
**Exact base HEAD:** `cbf008ac9e5ae87ac7654e358420fce63b2f8246`
**Base commit:** `AD-722b-5a: wire federation avatar telemetry relay (closes #659)`
**Numbering verified:** highest shipped top-level is **AD-1123**; highest shipped bug fix is **BF-672**; **BF-673** is the next sequential bug-fix number
**Dependencies:** AD-914, AD-933a, AD-935, AD-967, AD-970, AD-975, AD-986a
**License disposition:** none; no dependency or absorbed external code
**Estimated tests:** 5 new tests plus 2 assertions in the existing AD-970 test module; no new test file

## Scope

Repair only the server-owned speaker provenance carried from group fan-out into the receiving `CognitiveAgent` prompt and the existing group-episode trigger field.

The implementation must guarantee:

1. an ordinary Captain-authored group turn still renders exactly `Captain says: <text>`;
2. a proactive agent-created kickoff renders `<opener callsign> says: <text>` to every recipient;
3. if a valid opener has no callsign, its stable agent id is used instead of `Captain`;
4. a cascade round whose body already contains per-speaker `callsign: text` lines renders as `Room conversation:` and is never relabeled as Captain speech;
5. ordinary 1:1 DMs remain byte-identical and ignore any stray `trigger_speaker` value;
6. `trigger_speaker` remains server-owned inside `_fan_one_round`; no client/API field is added;
7. AD-986a group-episode enrichment receives the same truthful opener label through its existing `trigger_speaker` argument;
8. participant selection, round ordering, convergence, reply text, persistence, trust, artifacts, Todos, EventLog behavior, and configuration remain unchanged.

No durable crew-session contract, orchestration change, async continuation, room dedup, EventLog tool, trust-policy change, HXI refresh, API route, config field, or YAML edit is authorized here.

---

## Problem and verified root cause

The live rolling-week review found 19 multi-agent rooms and 78 agent messages, including six duplicate `Cooperation Cluster Investigation` rooms. Agent-created rooms begin through:

1. `ProactiveCognitiveLoop._extract_and_execute_group_chats()` persists the agent opening;
2. `_kickoff_group_chat(thread_id, opener_id, opening_body)` calls `group_chat_fanout(..., opener_id=...)`;
3. `group_chat_fanout()` excludes `opener_id` from round zero, but still calls `_fan_one_round(..., trigger_speaker="Captain")`;
4. `_fan_one_round._send_one()` does not put any speaker provenance into `IntentMessage.params`;
5. `CognitiveAgent._build_user_message()` unconditionally renders `Captain says: {params['text']}` for every `direct_message`, including group kickoff and agent-to-agent cascade turns.

The result is a two-layer false attribution: the recipient prompt says the Captain authored an agent opener, and AD-986a's optional enriched group episode records `trigger_agent="Captain"` for the same turn. Cascade rounds are also labeled as Captain speech even though their body is a joined set of completed crew replies.

The existing code already has the right provenance carrier: `_fan_one_round(trigger_speaker=...)`. The fix is to carry that server-owned value through params and use one pure formatter at the prompt boundary.

## Pinned design decisions

### DD-1 - One server-owned group trigger label

Use the existing `_fan_one_round(..., trigger_speaker: str = "")` argument as the single source of truth.

- Captain round: exact label `Captain`.
- Agent kickoff: resolve `opener_id` through the already-built `_roster_callsigns` map; fallback to `opener_id`.
- Cascade round: keep the existing empty string because `trigger_body` already contains one `callsign: text` line per prior speaker.

Add `"trigger_speaker": trigger_speaker` to the server-constructed group `params`. Do not add it to Pydantic request models, thread metadata, `IntentMessage`, or any API body.

### DD-2 - Pure prompt-boundary formatter

Add one private static helper on `CognitiveAgent`:

```python
@staticmethod
def _format_direct_message_trigger(params: dict[str, Any]) -> str:
    ...
```

Exact behavior:

| Context | Output |
|---|---|
| `is_group_chat` false/missing | `Captain says: <text>` |
| group + non-empty string `trigger_speaker` | `<trimmed speaker> says: <text>` |
| group + empty/missing/non-string `trigger_speaker` | `Room conversation:\n<text>` |

The helper must use `str(params.get("text", ""))` for total formatting. The 1:1 branch must ignore `trigger_speaker`, preserving all existing `Captain says:` golden tests and preventing a caller-supplied 1:1 param from spoofing a different speaker.

Replace only the existing `_emit("captain_message", [f"Captain says: ..."])` payload with this helper's return. Keep the internal attention-bid source name `captain_message` unchanged; renaming it is unrelated context-assembler churn.

### DD-3 - No transcript or display mutation

This BF changes the LLM input label and existing episodic trigger provenance only. It must not rewrite the persisted opening message, prepend a visible callsign to the transcript, modify `per_agent_replies`, or add a UI badge. Persisted `author_id`/`role` already carry message authorship correctly.

### DD-4 - No new broad sanitization or schema

The label comes from server-owned callsign/agent-id state, not an untrusted request field. Do not create a new schema, config knob, regex, storage column, or transport field. Existing agent-id/callsign boundaries remain authoritative.

### DD-5 - Preserve all fan-out mechanics

Do not change `opener_id` exclusion, `_assemble_speaker_signals`, `ChatFacilitator`, round limits, broadcast mode, convergence, `[NO_RESPONSE]`, message persistence, episodic content, or conversation trust. Only the already-computed speaker label changes.

## Build

### Section 1 - Red-first provenance tests

Edit `tests/test_ad970_agent_kickoff.py` first.

1. In the enabled kickoff test, retain the captured intents and assert the recipient intent carries `params["trigger_speaker"] == "Scout"`.
2. In the no-`opener_id` Captain test, assert every captured intent carries exact `"Captain"`.
3. Add pure formatter tests using `CognitiveAgent._format_direct_message_trigger`:
   - group opener `Scout` -> `Scout says: Status?`;
   - group with empty/missing speaker and joined peer lines -> starts `Room conversation:\n` and contains no `Captain says:`;
   - 1:1 with a stray `trigger_speaker="Scout"` -> exact `Captain says: Status?`.
4. Add an end-to-end kickoff case whose callsign map omits the opener and assert
   the recipient param uses the exact stable opener id (`scout1`), never
   `Captain`.
5. Add an enriched-memory kickoff case with a recording episodic store and
   `memory.group_episode_enrichment_enabled=True`; assert the stored episode's
   `anchors.trigger_agent == "Scout"` and its user input begins with
   `[group chat] Scout:`. This must fail red on the current hardcoded Captain
   label.
6. Run only `tests/test_ad970_agent_kickoff.py` before production edits. Record the failures. The current base must fail because the params key and formatter do not exist and the enriched episode records Captain.

Do not weaken existing opener-exclusion, grounding, or disabled-path assertions.

### Section 2 - Fan-out provenance

In `src/probos/routers/thread_fanout.py`:

1. Keep `_roster_callsigns` as the existing one-read callsign map.
2. Immediately before round zero, compute a local speaker label:
   - default `"Captain"`;
   - if `opener_id` is truthy, `_roster_callsigns.get(opener_id) or opener_id`.
3. Pass that label as `_fan_one_round(..., trigger_speaker=<label>)` instead of the hardcoded `"Captain"`.
4. In `_send_one`'s server-constructed params dict, add `"trigger_speaker": trigger_speaker` next to `"is_group_chat": True`.

Do not resolve callsigns again, mutate the roster, or put the value into client-authored metadata.

### Section 3 - Prompt rendering

In `src/probos/cognitive/cognitive_agent.py`:

1. Add the pure static helper from DD-2 near `_build_user_message` or the other direct-message formatting helpers.
2. Replace only the hardcoded `Captain says:` emit payload with the helper result.
3. Keep all preceding/following attention bids and their order unchanged.

### Section 4 - Regression gates and closeout

Run the exact gates in the execution prompt. After all pass and the Builder completes three review passes:

1. prepend one concise **BF-673 shipped** entry to `PROGRESS.md` with the exact test counts, truthful kickoff/cascade provenance, unchanged 1:1 behavior, no config/YAML/API/UI changes, and unchanged AD-1123 ceiling / new BF-673 ceiling;
2. do not edit `DECISIONS.md`, roadmap, era files, or any config;
3. retain both Architect prompts byte-for-byte;
4. commit locally with `BF-673: correct group trigger provenance`;
5. do not push and do not mutate GitHub.

## Acceptance criteria

1. Agent-created kickoff recipients receive exact server-owned opener callsign provenance.
2. Missing opener callsign falls back to the stable opener id, never `Captain`.
3. Captain-authored group turns still carry/render exact `Captain` provenance.
4. Unlabeled cascade context renders as `Room conversation`, not Captain speech.
5. Existing opener exclusion and bounded fan-out behavior are unchanged.
6. Existing AD-986a group enrichment uses the truthful round-zero label through the same argument; Captain and cascade behavior remain as specified.
7. Every existing 1:1 `Captain says:` golden remains green; a stray 1:1 `trigger_speaker` is ignored.
8. No persisted transcript body, response body, room title, participant set, trust record, EventLog row, artifact, Todo, work item, API response, event type, or UI state changes.
9. No config model or `config/system.yaml` change.
10. Tests use the existing real `ChatThreadStore` and `IntentBus` harness; no `MagicMock` at substrate boundaries.
11. Exact Gate 1, Gate 2, and Gate 3 pass at or above their pinned baselines plus the new assertions/tests, with no `RuntimeWarning`.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do not build here

- No durable room-session contract (AD-1124).
- No room-bound AgenticLoop execution or artifacts (AD-1125+).
- No async session runner/restart recovery.
- No Captain/self-originated ingress redesign or semantic room dedup.
- No EventLog read tool or `/api/system/events` endpoint.
- No trust/conversation-policy change.
- No task completion notifier or delivery metrics.
- No HXI room-state projection or live refresh.
- No `IntentMessage`, `BaseAgent`, or store schema change.
- No config/YAML/dependency/standing-order change.
- No new AD number, decision entry, roadmap entry, GitHub mutation, or push.

## Exact allowlist

### Production

- `src/probos/routers/thread_fanout.py`
- `src/probos/cognitive/cognitive_agent.py`

### Tests

- `tests/test_ad970_agent_kickoff.py`

### Architect documents - retain byte-for-byte

- `prompts/bf-673-group-trigger-provenance.md`
- `prompts/bf-673-group-trigger-provenance-execution.md`

### Conditional closeout only

- `PROGRESS.md`

No other path is authorized. A needed edit outside the allowlist is a hard stop.

## Exact base hashes

These hashes are authoritative before the Builder starts:

| Path | SHA-256 |
|---|---|
| `src/probos/routers/thread_fanout.py` | `63baf267b488bac302cf5d6a9a573cfde222758da5790cbea3e089fa69ad7e67` |
| `src/probos/cognitive/cognitive_agent.py` | `dbb63f7d18d558257eacee72db010c170852caa9ee0936d7ead2fb6f7c3d8cae` |
| `tests/test_ad970_agent_kickoff.py` | `8942eb6d03b1757bc66dda56c9fd0bad38f48c667d9d899e0dddc863d369565c` |

Any mismatch before implementation is a hard stop for Architect re-verification. Do not regenerate against a moved base.

## Exact test gates

All commands run from `D:\ProbOS`, serially, with a unique `PROBOS_DATA_DIR`, no pytest cache, short tracebacks, and `RuntimeWarning` promoted to error. Do not use `-n auto`.

Pinned exact-base baselines:

- Gate 1: **25 passed**; expected post-build **30 passed**.
- Gate 2: **48 passed**.
- Gate 3: **99 passed**.

The execution prompt contains the exact commands.

## Hard stops

Stop and return to the Architect if:

1. HEAD or any base hash differs;
2. initial status contains anything beyond the two Architect prompts;
3. the fix needs a new request/API field, store schema, config, event type, or file outside the allowlist;
4. any 1:1 golden changes;
5. a test requires client-supplied speaker provenance;
6. any focused failure falsifies the local hypothesis; or
7. a serial regression persists outside BF-673.

## Verified against codebase (2026-07-17)

- Exact clean `main` HEAD: `cbf008ac9e5ae87ac7654e358420fce63b2f8246`.
- `proactive.py` calls `group_chat_fanout(..., opener_id=opener_id)` from `_kickoff_group_chat`.
- `thread_fanout.py` declares `_fan_one_round(..., trigger_speaker: str = "")` and uses it for AD-986a episode enrichment.
- `thread_fanout.py` hardcodes round-zero `trigger_speaker="Captain"` even when `opener_id` is present.
- `_send_one` server-builds group params and currently omits speaker provenance.
- `cognitive_agent.py` unconditionally emits `Captain says:` on every direct-message prompt.
- `test_ad970_agent_kickoff.py` already captures the exact `IntentMessage` objects and uses real `ChatThreadStore`/`IntentBus` fixtures.
- Baselines independently run: 25 + 48 + 99 passed, no warnings.
- Repository ceilings independently grepped: AD-1123 / BF-672; no AD-1124 or BF-673 exists.

## Pre-dispatch checklist

- [x] BF-673 is the next sequential bug-fix number; no AD minted.
- [x] Correct repository: OSS behavior only; no commercial content.
- [x] Every file, symbol, caller, and signature above verified against exact HEAD.
- [x] Both consumers of `trigger_speaker` identified: recipient params/rendering and AD-986a episode enrichment.
- [x] Every Build item maps to Acceptance and named tests.
- [x] No store, SQLite, gate, destructive intent, or dependency is introduced.
- [x] 1:1 byte-identity and group edge cases are specified.
- [x] Async hygiene unchanged; no task is created.
- [x] Layer discipline preserved: router computes server provenance; cognitive layer formats its own prompt.
- [x] Hard stops and exact allowlist are explicit.
- [x] Engineering-principles compliance line is present.
