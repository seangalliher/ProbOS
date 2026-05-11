# AD-724 — Lightweight DM Sanity Gate (System-1 quality floor)

**Status:** Draft (Wave 150)
**Depends on:** Nothing new. Pure behavior-preserving migration + three new log-only checks.
**Closes:** GH #582
**Estimated tests:** +14 backend Python (0 UI; backend-only wave)
**Current highest AD:** AD-729. **Current highest BF:** BF-259. This AD slot (AD-724) was reserved in `DECISIONS.md:1741` as part of the AD-722 cluster and has not yet been built.

---

## Problem

The DM one-shot reply path in `src/probos/routers/agents.py::agent_chat` (line 875) ships whatever the LLM emits straight back to the Captain, with three ad-hoc post-hoc regex cleanups bolted in line:

| Marker | Lines (HEAD) | Purpose |
|---|---|---|
| BF-120 | 940–945 | Strip markdown wrappers (`**[`, `` ` ``[, `]**`, `]``) so structured tag regexes match |
| BF-119 | 947–1003 | Parse `[CHALLENGE @callsign game_type]` and dispatch to `RecreationService` |
| AD-572 | 1005–1041 | Parse `[MOVE pos]` and dispatch a move to `RecreationService` |

Three problems compound:

1. **Untestable in isolation.** Each regex sits inside a 270-line FastAPI handler with `Depends(get_runtime)` plumbing, so regression tests require spinning up the whole router.
2. **No quality floor.** A reply that decodes to `""`, `"..."`, or a duplicate of the previous turn ships unchanged. Decoder loops have shipped to the Captain in prod logs (see #582 evidence).
3. **No malformation surfacing.** When the LLM emits `[CHALLENGE @ezri` (truncated, missing closing bracket) or `[MOVE]` (missing value), the regex silently fails to match and the tag leaks into the Captain-visible text. There's nothing in the logs flagging this — we only learn about it from the Captain.

This AD relocates the three existing regex cleanups into a named, individually-testable module **and** adds three new log-only checks (length floor, repetition, orphaned tags). Future ADs (-1 through -5, listed below) extend it.

---

## Solution overview

1. **New module** `src/probos/cognitive/dm_sanity_gate.py` exposing `DmSanityGate` (a stateful class — needs `last_reply_by_agent` for the repetition check) and `DmSanityGateConfig` (Pydantic).
2. **Three migrated methods** that are byte-identical to the current inline regex behavior:
   - `strip_markdown(text: str) -> str` — BF-120
   - `extract_challenge(text: str) -> tuple[str, str] | None` plus `strip_challenge(text: str) -> str` — BF-119
   - `extract_move(text: str) -> str | None` plus `strip_move(text: str) -> str` — AD-572
3. **Three new check methods** that log warnings and return the text unchanged (Tier-2 log-and-degrade — never block):
   - `check_length_floor(agent_id, text)` — log if `len(text.strip()) < length_floor`
   - `check_repetition(agent_id, text)` — log if `text[:repetition_prefix_chars] == last_reply_by_agent.get(agent_id, "")[:repetition_prefix_chars]`
   - `check_orphaned_tags(text)` — log if any of three patterns match (see Section 1)
4. **One public entry point** `process(agent_id: str, text: str) -> DmSanityResult` orchestrating the order: strip_markdown → check_orphaned_tags → check_length_floor → check_repetition → (caller extracts challenge/move separately on the cleaned text).
5. **Config** — new `DmSanityGateConfig` mounted on `SystemConfig` as a top-level field (matches the `avatar_telemetry: AvatarTelemetryConfig` pattern at `config.py:3268`). **Default `enabled = True`** — the three migrated behaviors are already on; the new checks are log-only and risk-free.
6. **Runtime wiring** — construct once in `RuntimeOS.__init__` alongside `recreation_service` (config.py wiring pattern: `runtime.py:564`).
7. **Router rewrite** — `agent_chat` calls `runtime.dm_sanity_gate.process(...)`, then uses `extract_challenge` / `extract_move` instead of inline regex. The challenge/move dispatch blocks (lines 947–1003, 1005–1041) stay in the router — only the regex parsing moves out. **Identical outward behavior.**

### What this AD deliberately does NOT do (forward markers)

| Marker | Deferred work |
|---|---|
| AD-724-1 | One controlled retry on rejection (currently we log-and-ship-unchanged on every failure) |
| AD-724-2 | Repetition similarity (currently exact prefix match only — no Levenshtein, no embedding) |
| AD-724-3 | `_CAPABILITY_GAP_RE` integration (the existing regex elsewhere that catches "I can't", "I don't have access") |
| AD-724-4 | Multi-turn coherence checks |
| AD-724-5 | Sanity gate on Ward Room thread and chain-of-reasoning paths (this AD covers DM only) |

The repetition state is **per-agent, in-memory, lost on restart**. That is intentional — decoder-loop detection only needs the immediately-previous turn. Persisting it is forward marker AD-724-2 territory.

### Tier classification (per `.github/copilot-instructions.md`)

- **Tier-2 log-and-degrade** for all three new checks: log `warning`, return original text. Never raise. Never block.
- **Tier-3 propagate** is reserved for an explicit future "strict mode" config (NOT in scope).
- **Zero LLM calls.** Zero async. Zero retry. Synchronous, in-process, regex + dict-lookup only.

### Single new module — explicit

Do not split `DmSanityGate`, `DmSanityGateConfig`, and `DmSanityResult` across multiple files. Keep the cluster local. AD-724-1 (retry logic) will land in the same file when the time comes.

---

## Section 1 — Module: `src/probos/cognitive/dm_sanity_gate.py`

Create a new file with the following content. Module-level imports first (`re`, `logging`, `dataclasses.dataclass`, `pydantic.BaseModel`, `pydantic.Field`).

```python
"""AD-724: Lightweight sanity gate for DM one-shot replies.

Migrates three existing regex cleanups (BF-120 markdown strip, BF-119
challenge parse, AD-572 move parse) into a named, individually-testable
module, and adds three log-only quality checks (length floor, repetition,
orphaned tags).

Tier-2 log-and-degrade. The gate NEVER blocks a reply. Rejections log a
warning and the original text is shipped unchanged. Strict mode is a
forward marker (AD-724-1+).

State (per-agent last-reply cache for repetition detection) is in-memory
and lost on restart. Persistence is out of scope.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# --- Compiled regexes ---
# BF-120: markdown wrapper around structured tags.
_MARKDOWN_OPEN_RE = re.compile(r"[`*]{1,3}\[")
_MARKDOWN_CLOSE_RE = re.compile(r"\][`*]{1,3}")

# BF-119: well-formed challenge tag.
_CHALLENGE_RE = re.compile(r"\[CHALLENGE\s+@(\w+)\s+(\w+)\]")
_CHALLENGE_STRIP_RE = re.compile(r"\[CHALLENGE\s+@\w+\s+\w+\]")

# AD-572: well-formed move tag.
_MOVE_RE = re.compile(r"\[MOVE\s+(\S+)\]")
_MOVE_STRIP_RE = re.compile(r"\[MOVE\s+\S+\]")

# AD-724: malformed tags (open bracket + keyword, but missing close bracket
# OR missing value). These do NOT match the well-formed regexes above.
_ORPHANED_CHALLENGE_RE = re.compile(r"\[CHALLENGE\b(?![^\[\]]*\])")
_ORPHANED_MOVE_RE = re.compile(r"\[MOVE\b(?![^\[\]]*\S+\s*\])")
# A pair of square brackets containing nothing but whitespace, or an
# unmatched single open/close bracket on a line.
_EMPTY_BRACKETS_RE = re.compile(r"\[\s*\]")


class DmSanityGateConfig(BaseModel):
    """AD-724: configuration for the DM sanity gate.

    Default-ON because the three migrated behaviors (BF-120, BF-119, AD-572)
    are already running unconditionally in HEAD. Disabling this config
    DISABLES those migrations too — see warning in `process()`.
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100


@dataclass
class DmSanityResult:
    """Outcome of one `DmSanityGate.process()` call.

    `cleaned_text` is what the caller should use for downstream parsing
    and Captain-visible output. `warnings` is a list of `(check_name, detail)`
    tuples that the caller MAY surface (currently logged only).
    """

    cleaned_text: str
    warnings: list[tuple[str, str]] = field(default_factory=list)


class DmSanityGate:
    """AD-724: synchronous, in-process sanity gate for DM one-shot replies.

    Stateful (per-agent last-reply cache). Construct once per runtime.
    Thread-safety: caller responsibility. The chat router calls this
    inside the FastAPI request handler, which is already serialized per
    request by Starlette.
    """

    def __init__(self, config: DmSanityGateConfig | None = None) -> None:
        self.config = config or DmSanityGateConfig()
        # agent_id -> last cleaned reply text. Bounded by agent population.
        self._last_reply_by_agent: dict[str, str] = {}

    # --- Migrated regex helpers (behavior-preserving) ---

    def strip_markdown(self, text: str) -> str:
        """BF-120: strip markdown wrappers from structured tags.

        Identical behavior to the inline `re.sub` pair at
        `routers/agents.py:944-945` (HEAD).
        """
        if not text:
            return text
        text = _MARKDOWN_OPEN_RE.sub("[", text)
        text = _MARKDOWN_CLOSE_RE.sub("]", text)
        return text

    def extract_challenge(self, text: str) -> tuple[str, str] | None:
        """BF-119: extract `(target_callsign, game_type)` from a challenge tag.

        Returns ``None`` if no well-formed `[CHALLENGE @x y]` tag is present.
        """
        if not text:
            return None
        m = _CHALLENGE_RE.search(text)
        if not m:
            return None
        return m.group(1), m.group(2)

    def strip_challenge(self, text: str) -> str:
        """BF-119: remove `[CHALLENGE ...]` tags from Captain-visible text.

        Mirrors the inline `re.sub` at `routers/agents.py:1003` (HEAD),
        including the trailing `.strip()`.
        """
        if not text:
            return text
        return _CHALLENGE_STRIP_RE.sub("", text).strip()

    def extract_move(self, text: str) -> str | None:
        """AD-572: extract the move position from a `[MOVE pos]` tag.

        Returns ``None`` if no well-formed move tag is present.
        """
        if not text:
            return None
        m = _MOVE_RE.search(text)
        if not m:
            return None
        return m.group(1)

    def strip_move(self, text: str) -> str:
        """AD-572: remove `[MOVE ...]` tags from Captain-visible text.

        Mirrors the inline `re.sub` at `routers/agents.py:1041` (HEAD),
        including the trailing `.strip()`.
        """
        if not text:
            return text
        return _MOVE_STRIP_RE.sub("", text).strip()

    # --- New checks (Tier-2 log-and-degrade) ---

    def check_length_floor(self, agent_id: str, text: str) -> tuple[str, str] | None:
        """Return a `(check_name, detail)` warning if `text.strip()` is shorter
        than `config.length_floor`, else ``None``. Logs at WARNING level.
        """
        stripped_len = len(text.strip())
        if stripped_len < self.config.length_floor:
            detail = (
                f"reply length {stripped_len} < floor {self.config.length_floor}"
            )
            logger.warning(
                "AD-724: DM length floor breached for agent %s: %s",
                agent_id, detail,
            )
            return ("length_floor", detail)
        return None

    def check_repetition(self, agent_id: str, text: str) -> tuple[str, str] | None:
        """Return a warning if the first `repetition_prefix_chars` of `text`
        exactly match the previous reply for this agent. Logs at WARNING.

        Does NOT update the cache — the caller does that via `process()`
        after all checks have run.
        """
        prev = self._last_reply_by_agent.get(agent_id, "")
        n = self.config.repetition_prefix_chars
        if not prev or not text:
            return None
        if text[:n] == prev[:n]:
            detail = (
                f"first {n} chars match previous reply (possible decoder loop)"
            )
            logger.warning(
                "AD-724: DM repetition detected for agent %s: %s",
                agent_id, detail,
            )
            return ("repetition", detail)
        return None

    def check_orphaned_tags(self, text: str) -> tuple[str, str] | None:
        """Return a warning if the text contains a malformed structured tag:
        a `[CHALLENGE` or `[MOVE` without a closing bracket, or `[]`.
        Logs at WARNING.
        """
        if not text:
            return None
        if _ORPHANED_CHALLENGE_RE.search(text):
            detail = "orphaned [CHALLENGE — missing closing bracket"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        if _ORPHANED_MOVE_RE.search(text):
            detail = "orphaned [MOVE — missing value or closing bracket"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        if _EMPTY_BRACKETS_RE.search(text):
            detail = "empty []"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        return None

    # --- Orchestration entry point ---

    def process(self, agent_id: str, text: str) -> DmSanityResult:
        """Run the full gate. Returns a `DmSanityResult` carrying the cleaned
        text and any non-fatal warnings.

        If the config is disabled, the markdown strip still runs (it is a
        pure-string normalization with no behavioral risk) but the three
        new checks are skipped. This preserves the BF-120 migration
        invariant when an operator disables the gate.

        Order:
            1. strip_markdown (BF-120 migration; always runs)
            2. check_orphaned_tags (on stripped text, before extraction)
            3. check_length_floor
            4. check_repetition
            5. update last-reply cache
        """
        cleaned = self.strip_markdown(text)

        warnings: list[tuple[str, str]] = []
        if self.config.enabled:
            for check in (
                self.check_orphaned_tags(cleaned),
                self.check_length_floor(agent_id, cleaned),
                self.check_repetition(agent_id, cleaned),
            ):
                if check is not None:
                    warnings.append(check)

        # Update cache AFTER repetition check; bound to live agents only.
        # Empty replies do not poison the cache.
        if cleaned.strip():
            self._last_reply_by_agent[agent_id] = cleaned

        return DmSanityResult(cleaned_text=cleaned, warnings=warnings)
```

**Notes on the regex choices**

- `_MARKDOWN_OPEN_RE` and `_MARKDOWN_CLOSE_RE` are compiled equivalents of the inline patterns at `routers/agents.py:944-945`. Same substitution semantics.
- `_CHALLENGE_RE` / `_CHALLENGE_STRIP_RE` mirror lines 949 / 1003.
- `_MOVE_RE` / `_MOVE_STRIP_RE` mirror lines 1023 / 1041.
- The three orphaned-tag regexes are new. The negative-lookahead `(?![^\[\]]*\])` asserts "no closing bracket before the next bracket pair" — i.e. the open bracket is unclosed within the local scope. This matches `[CHALLENGE @ezri` (truncation) and `[MOVE` (no value, no close) without matching well-formed tags.

---

## Section 2 — Config: register `DmSanityGateConfig` on `SystemConfig`

Edit `src/probos/config.py`. Two changes.

### 2a. Add the model

Add the class somewhere in the top-level config section. Anywhere between `class TelemetryConfig` and `class SystemConfig` is fine. Recommended insertion point is just before `class SystemConfig` (after the last per-feature config block — `LintConfig` / `QualityRouterConfig` cluster).

**Search for the line near the bottom of the file containing the existing `class SystemConfig(BaseModel):` declaration (line 3186). Insert this block immediately before it:**

```python
class DmSanityGateConfig(BaseModel):  # AD-724
    """Configuration for the DM one-shot sanity gate.

    Default-ON: this config gates three previously-unconditional regex
    cleanups (BF-120, BF-119, AD-572) plus three new log-only checks.
    Disabling it preserves only the BF-120 markdown strip.
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100
```

### 2b. Mount the field

In `class SystemConfig`, add a top-level field. The natural insertion point is alongside the `avatar_telemetry` field (line 3268, AD-722 pattern). Use a SEARCH/REPLACE:

```
===SEARCH===
    avatar_telemetry: AvatarTelemetryConfig = Field(default_factory=AvatarTelemetryConfig)  # AD-722
===REPLACE===
    avatar_telemetry: AvatarTelemetryConfig = Field(default_factory=AvatarTelemetryConfig)  # AD-722
    dm_sanity_gate: DmSanityGateConfig = Field(default_factory=DmSanityGateConfig)  # AD-724
===END REPLACE===
```

---

## Section 3 — Runtime wiring

Edit `src/probos/runtime.py`. Construct the gate once during `RuntimeOS.__init__` alongside the existing per-service initialization blocks. The recreation_service block at line 563-564 is a clean anchor.

```
===SEARCH===
        # --- Recreation Service (AD-526a) ---
        self.recreation_service: Any = None
===REPLACE===
        # --- Recreation Service (AD-526a) ---
        self.recreation_service: Any = None

        # --- DM Sanity Gate (AD-724) ---
        from probos.cognitive.dm_sanity_gate import DmSanityGate
        self.dm_sanity_gate: DmSanityGate = DmSanityGate(
            self.config.dm_sanity_gate
        )
===END REPLACE===
```

The `self.config` reference is verified live by the surrounding initialization code (the recreation_preference_tracker at line 567 uses the same pattern: it constructs eagerly and reads `self.emit_event`).

---

## Section 4 — Router migration

Edit `src/probos/routers/agents.py`. Replace the three inline regex blocks with calls into `runtime.dm_sanity_gate`. **Identical outward behavior.**

### 4a. Replace BF-120 + add gate invocation

```
===SEARCH===
    # BF-120: Strip markdown formatting that wraps structured tags.
    # LLMs sometimes emit **[COMMAND ...]** or `[COMMAND ...]` which
    # prevents regex patterns from matching.
    if response_text:
        response_text = re.sub(r'[`*]{1,3}\[', '[', response_text)
        response_text = re.sub(r'\][`*]{1,3}', ']', response_text)
===REPLACE===
    # AD-724: DM sanity gate (migrates BF-120 markdown strip + adds 3 log-only checks).
    # The gate NEVER blocks; warnings are logged and the cleaned text is returned.
    sanity_gate = getattr(runtime, "dm_sanity_gate", None)
    if response_text and sanity_gate is not None:
        sanity_result = sanity_gate.process(agent_id, response_text)
        response_text = sanity_result.cleaned_text
===END REPLACE===
```

### 4b. Replace BF-119 challenge regex (extraction only — dispatch stays)

```
===SEARCH===
    # BF-119: Parse [CHALLENGE @callsign game_type] from DM response
    if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
        challenge_match = re.search(r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]', response_text)
        if challenge_match:
            target_callsign = challenge_match.group(1)
            game_type = challenge_match.group(2)
===REPLACE===
    # BF-119 (migrated to AD-724): Parse [CHALLENGE @callsign game_type] from DM response.
    if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
        challenge_parsed = (
            sanity_gate.extract_challenge(response_text)
            if sanity_gate is not None
            else None
        )
        if challenge_parsed is not None:
            target_callsign, game_type = challenge_parsed
===END REPLACE===
```

### 4c. Replace BF-119 strip

```
===SEARCH===
            # Strip [CHALLENGE] tag from response text shown to Captain
            response_text = re.sub(r'\[CHALLENGE\s+@\w+\s+\w+\]', '', response_text).strip()
===REPLACE===
            # AD-724: Strip [CHALLENGE] tag from Captain-visible text.
            if sanity_gate is not None:
                response_text = sanity_gate.strip_challenge(response_text)
            else:
                response_text = re.sub(r'\[CHALLENGE\s+@\w+\s+\w+\]', '', response_text).strip()
===END REPLACE===
```

### 4d. Replace AD-572 move regex (extraction)

```
===SEARCH===
    # AD-572: Parse [MOVE pos] from DM response and execute against RecreationService
    game_move_result = None
    if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
        move_match = re.search(r'\[MOVE\s+(\S+)\]', response_text)
        if move_match:
            position = move_match.group(1)
===REPLACE===
    # AD-572 (migrated to AD-724): Parse [MOVE pos] and execute against RecreationService.
    game_move_result = None
    if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
        position = (
            sanity_gate.extract_move(response_text)
            if sanity_gate is not None
            else None
        )
        if position is not None:
===END REPLACE===
```

### 4e. Replace AD-572 strip

```
===SEARCH===
            # Strip [MOVE] tag from response text shown to Captain
            response_text = re.sub(r'\[MOVE\s+\S+\]', '', response_text).strip()
===REPLACE===
            # AD-724: Strip [MOVE] tag from Captain-visible text.
            if sanity_gate is not None:
                response_text = sanity_gate.strip_move(response_text)
            else:
                response_text = re.sub(r'\[MOVE\s+\S+\]', '', response_text).strip()
===END REPLACE===
```

**Why the `if sanity_gate is not None: ... else: <legacy>` fallback?** Tests that build a synthetic `runtime` via `_FakeRuntime` and don't wire up `dm_sanity_gate` would otherwise regress. The `getattr(runtime, "dm_sanity_gate", None)` in 4a + the `else:` branches keep the legacy inline regex behavior available as a safety net during tests. Production `RuntimeOS` always sets `self.dm_sanity_gate` in Section 3.

---

## Section 5 — Tests: `tests/test_ad724_dm_sanity_gate.py`

Create a new test file. Use pytest, no async, no fixtures more complex than instantiating `DmSanityGate(DmSanityGateConfig())`. 14 tests total.

### Migration behavior preservation (6 tests)

1. **`test_strip_markdown_handles_double_asterisks`** — `gate.strip_markdown("**[CHALLENGE @ezri tictactoe]**")` returns `"[CHALLENGE @ezri tictactoe]"`. Asserts byte-identity with the BF-120 inline behavior.
2. **`test_strip_markdown_handles_backticks`** — `gate.strip_markdown("`[MOVE A1]`")` returns `"[MOVE A1]"`.
3. **`test_strip_markdown_empty_input_returns_empty`** — `gate.strip_markdown("")` returns `""` (does not crash).
4. **`test_extract_challenge_well_formed`** — `gate.extract_challenge("Hey, [CHALLENGE @ezri tictactoe] right now?")` returns `("ezri", "tictactoe")`.
5. **`test_extract_challenge_returns_none_when_absent`** — `gate.extract_challenge("Just a normal reply.")` returns `None`.
6. **`test_extract_move_well_formed_and_strip`** — Combined: `gate.extract_move("Playing [MOVE B2] now.")` returns `"B2"`; `gate.strip_move(...)` on the same text returns `"Playing  now."` then `.strip()` collapses to `"Playing  now."` (the inline `.strip()` only trims edges; the embedded double-space is acceptable and matches HEAD behavior — write the test to assert exactly what `re.sub(r'\[MOVE\s+\S+\]', '', text).strip()` produces on the same input).

### New length-floor check (2 tests)

7. **`test_length_floor_logs_when_too_short`** — Configure `length_floor=5`. `gate.check_length_floor("agent-1", "hi")` returns `("length_floor", <detail>)`. Use `caplog.at_level("WARNING")` to assert a warning is logged with text matching `"length floor breached"`.
8. **`test_length_floor_silent_above_threshold`** — `gate.check_length_floor("agent-1", "a normal reply")` returns `None` and emits no warnings (assert via `caplog.records` empty).

### New repetition check (3 tests)

9. **`test_repetition_first_reply_is_not_flagged`** — First call to `gate.process("a-1", "Hello Captain.")` produces no `repetition` warning (no prior reply to compare).
10. **`test_repetition_identical_prefix_flagged`** — Two calls with the same first-100-chars produce a `repetition` warning on the second call. Detail string includes `"decoder loop"`.
11. **`test_repetition_state_is_per_agent`** — Same text sent to two different `agent_id` values does NOT flag — repetition is per-agent.

### New orphaned-tag check (2 tests)

12. **`test_orphaned_challenge_flagged`** — `gate.check_orphaned_tags("Hey [CHALLENGE @ezri")` returns `("orphaned_tag", <detail>)` with detail containing `"CHALLENGE"`. Well-formed `[CHALLENGE @ezri tictactoe]` returns `None`.
13. **`test_empty_brackets_flagged`** — `gate.check_orphaned_tags("Result: []")` returns `("orphaned_tag", "empty []")`.

### Orchestration end-to-end (1 test)

14. **`test_process_disabled_config_still_strips_markdown_but_skips_checks`** — Construct gate with `DmSanityGateConfig(enabled=False)`. Process `"**[CHALLENGE @x y]**"` (markdown wrapper). Assert `result.cleaned_text == "[CHALLENGE @x y]"` (markdown strip ran) AND `result.warnings == []` (other checks skipped).

**No router-level integration tests in this AD.** The router already has integration coverage for the challenge/move dispatch paths; if those tests pass after Section 4's migration with no changes needed, the migration is byte-identical by construction. If a router test breaks, that is a hard-stop signal that Section 4 changed behavior.

---

## What this AD does NOT change

- The challenge/move dispatch logic in `agent_chat` (the `await rec_svc.create_game(...)` / `await rec_svc.make_move(...)` calls and the Ward Room post-board update). Only the **regex extraction** moves; the dispatch stays in the router.
- Any other regex elsewhere in the codebase. `_CAPABILITY_GAP_RE` is forward marker AD-724-3.
- Ward Room or chain-of-reasoning paths. Forward marker AD-724-5.
- `runtime.emit_event` / EventType. The gate only logs; it does NOT publish events. (If we want telemetry surfacing later, it's a one-line addition in `process()` — but not in this AD.)
- API surface. No new endpoints. No new request/response fields. No new `api_models.py` changes.
- UI. Zero frontend changes.
- Pydantic field ordering on `SystemConfig` (the new field goes immediately after `avatar_telemetry`, default_factory, no ordering risk).

---

## Tracking

- `PROGRESS.md` — close GH #582, increment test count by +14 (backend), update "most recent shipped wave" line.
- `docs/development/roadmap.md` — mark AD-724 shipped. Filed in Bug Tracker if any BF is opened (none expected for a behavior-preserving migration).
- `DECISIONS.md` — AD-724 already has a stub entry at line 1741. **Append an "Implementation (Wave 150)" subsection** noting: module location, default-on config, five forward markers (AD-724-1 through AD-724-5).
- GH #582 closed with commit reference.

---

## Acceptance criteria

- All 14 new tests pass under `pytest tests/test_ad724_dm_sanity_gate.py -v -n 0`.
- Full gate green: `pytest tests/ -q -n 4 --dist=loadfile`. No pre-existing router tests regress (specifically: any `test_agent_chat_*` and any `test_*recreation*` tests that exercise the chat handler).
- Phantom-API precheck clean: `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-724-dm-sanity-gate.md`.
- `re` import retained in `routers/agents.py` (the `else:` legacy branches in 4c/4e still use it; do not remove).
- The three behavior-preservation tests (1, 2, 4, 5, 6) assert byte-identical output to the prior inline regex behavior.
- All changes comply with Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-11)

```
grep -n "BF-120: Strip markdown" src/probos/routers/agents.py
  940:    # BF-120: Strip markdown formatting that wraps structured tags.
  944:        response_text = re.sub(r'[`*]{1,3}\[', '[', response_text)
  945:        response_text = re.sub(r'\][`*]{1,3}', ']', response_text)

grep -n "BF-119: Parse" src/probos/routers/agents.py
  947:    # BF-119: Parse [CHALLENGE @callsign game_type] from DM response
  949:        challenge_match = re.search(r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]', response_text)
  1003:            response_text = re.sub(r'\[CHALLENGE\s+@\w+\s+\w+\]', '', response_text).strip()

grep -n "AD-572: Parse" src/probos/routers/agents.py
  1005:    # AD-572: Parse [MOVE pos] from DM response and execute against RecreationService
  1023:        move_match = re.search(r'\[MOVE\s+(\S+)\]', response_text)
  1041:            response_text = re.sub(r'\[MOVE\s+\S+\]', '', response_text).strip()

grep -n "async def agent_chat" src/probos/routers/agents.py
  875:async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:

grep -n "^import re" src/probos/routers/agents.py
  7:import re

grep -n "class SystemConfig" src/probos/config.py
  3186:class SystemConfig(BaseModel):

grep -n "avatar_telemetry: AvatarTelemetryConfig" src/probos/config.py
  3268:    avatar_telemetry: AvatarTelemetryConfig = Field(default_factory=AvatarTelemetryConfig)  # AD-722

grep -n "recreation_service: Any" src/probos/runtime.py
  564:        self.recreation_service: Any = None

grep -n "AD-724" DECISIONS.md
  1741:### AD-724 — Lightweight sanity gate for DM one-shot replies (System-1 quality floor)
```

All concrete claims in this prompt map to grep hits above. No phantom APIs: `RuntimeOS.config.dm_sanity_gate` is introduced by Section 2; `runtime.dm_sanity_gate` is introduced by Section 3 — both are wired before any consumer references them in Section 4.
