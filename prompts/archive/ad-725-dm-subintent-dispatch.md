# AD-725 — Targeted sub-intent dispatch on the DM one-shot path

**AD:** AD-725. **GH issue closed:** [#583](https://github.com/seangalliher/ProbOS/issues/583).
**Parent ADs:** AD-722 (telemetry addendum — System-1/System-2 ruling), AD-723 (sensorium dispatch unification), AD-723a-1 (DM_ONESHOT consumer side), AD-724 (DM sanity gate, planned), AD-726 (one-shot path refactor, planned).
**Wave:** 159. **Estimated tests:** +10 pytest. **Estimated wall-time:** ~2h. **Risk:** MED (introduces a new pre-LLM dispatch surface; contract MUST be "one lookup per turn, no side effects").

---

## Solution Overview

Chain reasoning has access to sub-intents mid-flight (`oracle_lookup`, `episodic_query`, `codebase_query`, `knowledge_load`). The DM one-shot path does not — Ezri answering "what was our last 1:1 about?" has only pre-loaded working memory; she can't reach for episodic memory before the LLM call.

This is the largest cognitive-parity gap between the System-1 (DM one-shot) and System-2 (chain) paths. Per the AD-722-addendum + AD-723 ruling, DM stays one-shot — but one-shot doesn't have to mean blind. **A targeted pre-LLM lookup, gated by a fast classifier, issues EXACTLY ONE scoped read before the LLM call.** The result lands as a sensorium block in the observation dict and renders into the prompt under a `--- Targeted Recall ---` heading.

**Hard contracts (the firewall):**
1. **At most one lookup per turn.** No chains, no follow-ups.
2. **Read-only.** No episodic write, no trust update, no Hebbian edge update, no consensus broadcast.
3. **Hard timeout** (default 500ms). Timeout → degrade silently (proceed without the recall block).
4. **No intent_bus broadcast.** Direct method calls on `runtime.oracle` / `runtime.episodic_memory` / `runtime.codebase_index`. The DM path is conversation, not work.

**Classifier as a `Protocol`** so the v1 regex/keyword ladder can be swapped for an embedding router (AD-725-2 forward marker) without touching the caller.

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | new `DmTargetedLookupConfig` Pydantic model + add `dm_targeted_lookup: DmTargetedLookupConfig = Field(default_factory=...)` to `SystemConfig`. | Per-store enables + timeout + classifier-tier selection. |
| `src/probos/cognitive/dm_targeted_lookup.py` | NEW (~250 lines) | `SubintentClassifier` Protocol, `RegexSubintentClassifier` v1 impl, `LookupDispatcher` orchestrator. |
| `src/probos/routers/agents.py` | ~875 (top of `agent_chat`, BEFORE the existing `_build_user_message` cascade) | Call dispatcher; inject result into observation/intent params. |
| `tests/test_ad725_dm_targeted_lookup.py` | NEW | 10 boundary tests. |

Live grep confirms:
- DM one-shot is dispatched from `routers/agents.py:agent_chat` at line 875. The downstream consumer is `cognitive_agent.py:_build_user_message` at line 5893 (DM path).
- `runtime.oracle`, `runtime.episodic_memory`, `runtime.codebase_index` are existing public attributes (greppable in `runtime.py`). `runtime.oracle` is the AD-686 public alias for the same `OracleService` instance held privately at `runtime._oracle_service` (see `runtime.py:1536-1537`).
- The integration seam per the issue body: BEFORE `_build_user_message` so the result is in the observation dict when assembly runs. Cleanest seam is in `agent_chat` directly — populate `req.params.targeted_recall` (or equivalent) before the `IntentMessage` is built for dispatch to the agent.
- AD-723 sensorium-path registration is the cleaner integration. But for v1 we inject directly via the IntentMessage params and have `_build_user_message` render the block. Path-scoped sensorium registration (`paths=(DM_ONESHOT,)`) is a forward marker (AD-725-1) — keeps the v1 surface tight.

---

## Section 1 — `DmTargetedLookupConfig` Pydantic model

In `src/probos/config.py`, add a new Pydantic model (alphabetical ordering — between existing models). Then add it as a field on `SystemConfig`.

```python
class DmTargetedLookupConfig(BaseModel):
    """AD-725: pre-LLM targeted sub-intent dispatch on the DM one-shot path.

    Default OFF — opt-in because the lookup adds latency (max(classifier,
    lookup) ≈ 100-300ms) and the v1 regex classifier is intentionally
    conservative. Per-store enables let the operator narrow the surface
    further.
    """

    enabled: bool = False
    classifier_tier: str = "regex"             # v1 ladder; "embedding" reserved for AD-725-2
    timeout_ms: int = 500                      # hard cap; lookup ABORTS on timeout
    enable_oracle: bool = True
    enable_episodic: bool = True
    enable_codebase: bool = False              # default OFF — codebase queries can be slow
    enable_knowledge: bool = True
    max_lookup_chars: int = 1500               # truncate lookup result before injection

    @field_validator("classifier_tier")
    @classmethod
    def _bound_classifier_tier(cls, v: str) -> str:
        allowed = {"regex", "embedding"}
        if v not in allowed:
            raise ValueError(
                f"classifier_tier must be one of {sorted(allowed)}, got {v!r}"
            )
        return v

    @field_validator("timeout_ms", "max_lookup_chars")
    @classmethod
    def _bound_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"must be >= 1, got {v}")
        return v
```

Add to `SystemConfig`:

```python
    dm_targeted_lookup: DmTargetedLookupConfig = Field(default_factory=DmTargetedLookupConfig)
```

**Builder MUST** locate the actual `SystemConfig` class in `config.py` (grep for `class SystemConfig`) and insert in alphabetical position among the other `Field(default_factory=...)` sub-configs.

---

## Section 2 — Classifier Protocol + regex v1 impl

Create `src/probos/cognitive/dm_targeted_lookup.py`:

```python
"""AD-725: targeted sub-intent dispatch on the DM one-shot path.

Contract:
  * AT MOST ONE lookup per DM turn. No chains.
  * Read-only — no episodic store, trust update, Hebbian edge, consensus.
  * Hard timeout (config.dm_targeted_lookup.timeout_ms). Timeout → None.
  * No intent_bus broadcast — direct method calls only.

Classifier is a Protocol so v1 regex can be swapped for embedding routing
later (AD-725-2 forward marker).
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from probos.config import DmTargetedLookupConfig

logger = logging.getLogger(__name__)

LookupType = Literal["oracle", "episodic", "codebase", "knowledge", "none"]


@dataclass(frozen=True)
class TargetedLookupResult:
    """Returned to the caller. ``None`` for the whole optional means "no
    lookup ran"; ``content=""`` with a non-none ``lookup_type`` means
    "lookup ran but returned empty" — caller treats both the same.
    """
    lookup_type: LookupType
    query: str
    content: str
    elapsed_ms: float


class SubintentClassifier(Protocol):
    """Pre-LLM intent-router. Returns at most one lookup_type + query."""

    def classify(self, message: str, *, agent_id: str) -> tuple[LookupType, str]:
        ...


# ── v1 regex ladder ──────────────────────────────────────────────────

_EPISODIC_PATTERNS = [
    re.compile(r"\b(last|previous|recent|earlier)\s+(time|conversation|chat|1:1|meeting)\b", re.I),
    re.compile(r"\bdid (we|you|i) (talk|discuss|mention)\b", re.I),
    re.compile(r"\bwhat (did|was) (we|you|i)\b.*\b(say|discuss|talk)\b", re.I),
    re.compile(r"\bremember when\b", re.I),
]

_CODEBASE_PATTERNS = [
    re.compile(r"\b(where|how)\s+(is|do|does|are)\b.*\b(implement|defined|located|coded)\b", re.I),
    re.compile(r"\b(grep|find|search)\s+(the\s+)?codebase\b", re.I),
    re.compile(r"\b(file|module|class|function)\s+(named|called)\b", re.I),
    re.compile(r"\bwhich (file|module|class)\b", re.I),
]

_KNOWLEDGE_PATTERNS = [
    re.compile(r"\b(ship'?s?\s+records?|knowledge\s+base|manual|standing\s+order)\b", re.I),
    re.compile(r"\baccording to\b.*\b(record|doc|manual|policy)\b", re.I),
]

_ORACLE_PATTERNS = [
    re.compile(r"\b(time|date|today|now|current)\b", re.I),
    re.compile(r"\bwhat (time|day|date)\b", re.I),
]


class RegexSubintentClassifier:
    """v1 ladder. Order: episodic → codebase → knowledge → oracle → none."""

    def classify(self, message: str, *, agent_id: str) -> tuple[LookupType, str]:
        if not message:
            return "none", ""
        for pats, name in (
            (_EPISODIC_PATTERNS, "episodic"),
            (_CODEBASE_PATTERNS, "codebase"),
            (_KNOWLEDGE_PATTERNS, "knowledge"),
            (_ORACLE_PATTERNS, "oracle"),
        ):
            for pat in pats:
                if pat.search(message):
                    return name, message  # type: ignore[return-value]
        return "none", ""


# ── Dispatcher ──────────────────────────────────────────────────────


class LookupDispatcher:
    """Runs the classifier, dispatches at most one read-only lookup."""

    def __init__(
        self,
        *,
        runtime: Any,
        config: "DmTargetedLookupConfig",
        classifier: SubintentClassifier | None = None,
    ) -> None:
        self._runtime = runtime
        self._cfg = config
        self._classifier = classifier or RegexSubintentClassifier()

    async def maybe_lookup(
        self, message: str, *, agent_id: str,
    ) -> TargetedLookupResult | None:
        """Returns a result OR None (no-op). Tier-2 — never raises."""
        if not self._cfg.enabled:
            return None
        try:
            lookup_type, query = self._classifier.classify(message, agent_id=agent_id)
        except Exception:
            logger.warning("AD-725: classifier raised; degrading", exc_info=True)
            return None
        if lookup_type == "none":
            return None
        if not self._is_lookup_enabled(lookup_type):
            return None
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            content = await asyncio.wait_for(
                self._dispatch(lookup_type, query, agent_id),
                timeout=self._cfg.timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            logger.info(
                "AD-725: lookup %s timed out for agent=%s after %d ms",
                lookup_type, agent_id, self._cfg.timeout_ms,
            )
            return None
        except Exception:
            logger.warning(
                "AD-725: lookup %s raised for agent=%s; degrading",
                lookup_type, agent_id, exc_info=True,
            )
            return None
        elapsed_ms = (loop.time() - t0) * 1000.0
        if not isinstance(content, str):
            logger.warning(
                "AD-725: lookup %s returned non-str (%s) — dropping",
                lookup_type, type(content).__name__,
            )
            return None
        truncated = content[: self._cfg.max_lookup_chars]
        return TargetedLookupResult(
            lookup_type=lookup_type,
            query=query[:500],
            content=truncated,
            elapsed_ms=elapsed_ms,
        )

    def _is_lookup_enabled(self, lookup_type: LookupType) -> bool:
        return {
            "oracle": self._cfg.enable_oracle,
            "episodic": self._cfg.enable_episodic,
            "codebase": self._cfg.enable_codebase,
            "knowledge": self._cfg.enable_knowledge,
        }.get(lookup_type, False)

    async def _dispatch(
        self, lookup_type: LookupType, query: str, agent_id: str,
    ) -> str:
        """Dispatch to the appropriate read-only surface. NO side effects.

        Builder MUST verify the exact method signatures by grepping the
        runtime — names below are the conventional public surfaces but
        the AD's contract is "whichever read-only entry point exists."
        """
        if lookup_type == "oracle":
            # AD-686 public alias: runtime.oracle is the OracleService instance.
            # Method is async def query(query_text, *, agent_id="", ...) -> list[OracleResult].
            oracle = getattr(self._runtime, "oracle", None)
            if oracle is None or not hasattr(oracle, "query"):
                logger.info(
                    "AD-725: oracle lookup unavailable on runtime (no runtime.oracle.query)",
                )
                return ""
            res = oracle.query(query, agent_id=agent_id)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        if lookup_type == "episodic":
            em = getattr(self._runtime, "episodic_memory", None)
            if em is None or not hasattr(em, "recall_for_agent"):
                logger.info(
                    "AD-725: episodic lookup unavailable (no runtime.episodic_memory.recall_for_agent)",
                )
                return ""
            # Verified: episodic.py:1900 — signature is (agent_id, query, k=5).
            res = em.recall_for_agent(agent_id, query, k=3)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        if lookup_type == "codebase":
            ci = getattr(self._runtime, "codebase_index", None)
            if ci is None or not hasattr(ci, "query"):
                logger.info(
                    "AD-725: codebase lookup unavailable (no runtime.codebase_index.query)",
                )
                return ""
            res = ci.query(query)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        if lookup_type == "knowledge":
            rs = getattr(self._runtime, "records_store", None)
            if rs is None or not hasattr(rs, "search"):
                logger.info(
                    "AD-725: knowledge lookup unavailable (no runtime.records_store.search)",
                )
                return ""
            res = rs.search(query)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        return ""

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(
                        " ".join(f"{k}={v}" for k, v in item.items())
                    )
                else:
                    parts.append(repr(item))
            return "\n".join(parts)
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        return repr(value)
```

**Builder verification step before integration:** grep `runtime.oracle`, `runtime.episodic_memory`, `runtime.codebase_index`, `runtime.records_store` and confirm the read-only method names used in `_dispatch`. The dispatcher is defensive (`hasattr` + degrade), so a wrong name returns `""` rather than crashing — but the wrong name silently disables the entire branch. Verified signatures (live grep, 2026-05-14):
- Oracle: `runtime.oracle.query(query_text, *, agent_id="", intent_type="", k_per_tier=5, tiers=None, ...) -> list[OracleResult]` — async, verified at `src/probos/cognitive/oracle_service.py:285`. `runtime.oracle` is the AD-686 public alias for `cog.oracle_service` (`runtime.py:1537`). Dispatcher passes `agent_id` positionally via kwarg; other kwargs use service defaults.
- Episodic: `episodic_memory.recall_for_agent(agent_id, query, k=5)` — verified at `src/probos/cognitive/episodic.py:1900` (kwarg is `k`, NOT `limit`). The Protocol dispatcher uses `k=3`.
- Codebase: `codebase_index.query(concept)` is verified in `.github/copilot-instructions.md` doc — public surface.
- Knowledge: `records_store.search(query)` — Builder MUST grep to confirm; if absent, the knowledge branch degrades cleanly.

Document any signature substitution in the AD-725 DECISIONS entry.

---

## Section 3 — Wire into `agent_chat`

In `src/probos/routers/agents.py:agent_chat` (line 875), add the dispatcher call near the top — AFTER the agent/crew validation but BEFORE the vision-pipeline branch:

```python
    # AD-725: targeted sub-intent dispatch (DM one-shot pre-LLM lookup).
    # Tier-2 — never blocks the DM. Result becomes a 'targeted_recall' field
    # on the IntentMessage params; rendered by _build_user_message under
    # a "--- Targeted Recall ---" heading.
    targeted_recall_block: str | None = None
    try:
        _dm_cfg = getattr(runtime.config, "dm_targeted_lookup", None)
        if _dm_cfg is not None and _dm_cfg.enabled:
            from probos.cognitive.dm_targeted_lookup import LookupDispatcher
            _dispatcher = LookupDispatcher(runtime=runtime, config=_dm_cfg)
            _result = await _dispatcher.maybe_lookup(
                req.message, agent_id=agent_id,
            )
            if _result is not None and _result.content:
                targeted_recall_block = (
                    f"--- Targeted Recall ({_result.lookup_type}) ---\n"
                    f"{_result.content}\n"
                    f"--- End Recall ---"
                )
                logger.info(
                    "AD-725: agent=%s lookup_type=%s elapsed_ms=%.1f chars=%d",
                    agent_id, _result.lookup_type,
                    _result.elapsed_ms, len(_result.content),
                )
    except Exception:
        logger.debug("AD-725: dispatcher branch failed", exc_info=True)
```

**Injection point in the prompt assembly:** the simplest seam is to prepend `targeted_recall_block` to `message_text` immediately before the IntentMessage is built:

```python
    if targeted_recall_block is not None:
        message_text = f"{targeted_recall_block}\n\n{message_text}"
```

Place this immediately before the IntentMessage / vision pipeline branch — the recall block must reach the agent's LLM call as part of the message context. Builder MUST verify the exact location of where `message_text` is finalized into an IntentMessage and insert the prepend BEFORE that finalization. Do NOT modify `_build_user_message` itself — that's a deeper refactor reserved for AD-726.

---

## Test plan (boundary tests)

Create `tests/test_ad725_dm_targeted_lookup.py` with 10 tests. Build a `_FakeRuntime` with stubbed `oracle` (matching the AD-686 public alias), `episodic_memory`, `codebase_index`, `records_store`. Each stub records call args.

1. `test_disabled_config_returns_none` — `enabled=False` → `maybe_lookup()` returns None, no stub called.
2. `test_classifier_none_returns_none` — message with no classifier match → returns None.
3. `test_episodic_path_hits_recall_for_agent` — "what did we discuss last time?" → routes to episodic, episodic stub called exactly once.
4. `test_codebase_path_disabled_by_default` — codebase-matching message + `enable_codebase=False` → returns None (codebase stub NEVER called).
5. `test_oracle_path_with_async_result` — oracle stub returns a coroutine → awaited and stringified.
6. `test_knowledge_path_with_missing_search_method` — `runtime.records_store` lacks `.search` → returns None (no crash).
7. `test_timeout_returns_none` — episodic stub sleeps longer than `timeout_ms` → returns None.
8. `test_classifier_exception_degrades` — inject a classifier that raises → returns None, no propagation.
9. `test_result_truncated_to_max_lookup_chars` — episodic returns very long string → result `.content` length ≤ `max_lookup_chars`.
10. `test_no_side_effects_on_runtime` — after `maybe_lookup()` runs, verify the fake runtime's `trust_network` / `intent_bus` / Hebbian routing stubs have ZERO recorded calls (asserts the firewall).

All tests use `_FakeRuntime` + `DmTargetedLookupConfig` directly — no need to boot a real ProbOS runtime.

---

## What this does NOT change

- The chain path / decomposer — unchanged.
- `_build_user_message` itself — receives a pre-augmented message text. Sensorium-path registration deferred to AD-725-1 forward marker.
- Trust / Hebbian / consensus / intent_bus — explicitly verified by test #10.
- Multi-step retrieval — the contract is one-lookup-per-turn. Future iteration goes to chain.
- Episodic write — DM lookup is read-only; episodic write happens AFTER the DM reply per the existing AD-723a-1 path.
- Per-agent sub-intent vocabulary — AD-725-3 forward marker (Counselor cares about emotional sub-intents; Worf cares about threat sub-intents).
- `prompts/BUILDER-EXECUTION-PLAN.md` — not edited.

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad725_dm_targeted_lookup.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

No UI changes — `npm run build` not required.

---

## Tracker updates

- `PROGRESS.md` — append closure line with test count delta.
- `docs/development/roadmap.md` — mark #583 closed; add forward markers AD-725-1 (sensorium-path registration), AD-725-2 (embedding-based classifier), AD-725-3 (per-agent sub-intent vocabulary).
- `DECISIONS.md` — append AD-725 entry. Document: (a) the four-contract firewall (one-lookup, read-only, timeout, no-broadcast); (b) the regex ladder vs embedding-router choice; (c) the integration seam (prepend at `agent_chat`, not inside `_build_user_message`); (d) the deferral of sensorium-path registration to AD-725-1.

Commit message:
```
AD-725: targeted sub-intent dispatch on DM one-shot path

Closes #583
```

---

## License Disposition

**All-internal Apache 2.0.** No new pip deps (stdlib `re`, `asyncio`, `dataclasses`, `typing.Protocol`). No new npm deps. No external services. No model weights — the v1 classifier is pure regex; the embedding-router forward marker (AD-725-2) would route through ProbOS's existing LLM client (no new dependency).

---

## Forward markers

- **AD-725-1** — sensorium-path registration (the lookup result registers as a `paths=(DM_ONESHOT,)` sensorium block via the AD-723 dispatcher, instead of being prepended raw to message text).
- **AD-725-2** — embedding-based classifier as drop-in `SubintentClassifier` Protocol implementation.
- **AD-725-3** — per-agent sub-intent vocabulary (Counselor's emotion-sub-intents, Worf's threat-sub-intents, Engineering's repo-state-sub-intents).
- **AD-725-4** — multi-store fan-out gated by classifier confidence (e.g. high-confidence episodic AND knowledge as a single concurrent lookup pair; still one "lookup phase" per turn).
- **AD-725-5** — `(text_hash, agent_id) -> TargetedLookupResult` LRU cache for repeat-query suppression. v1 ships without; the 500ms timeout + regex classifier sub-ms cost bound the worst-case latency. Trigger: embedding routing lands (AD-725-2) and per-turn cost rises.
- **AD-725-6** — `_stringify` Episode-dataclass branch (`f"- {ep.text}"` rows) for cleaner LLM context. v1 falls through to `repr()`; readable but verbose.

---

## Acceptance criteria

- All 10 new tests pass under `-n 0`.
- Full gate green.
- Test #10 (zero-side-effects) explicitly verifies no trust / Hebbian / intent_bus / consensus state changes.
- Default config has `enabled=False` — Captain explicitly opts in.
- Hard timeout enforced (default 500ms).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
grep -n "async def agent_chat" src/probos/routers/agents.py
  875: async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:

grep -n "def _build_user_message" src/probos/cognitive/cognitive_agent.py
  5893:     async def _build_user_message(self, observation: dict) -> str:

grep -n "DM_ONESHOT" src/probos/cognitive/cognitive_agent.py
  80:     DM_ONESHOT = "dm_oneshot"

grep -n "direct_message" src/probos/cognitive/cognitive_agent.py
  182: ... intent.intent == "direct_message"
  5910:         if intent_name == "direct_message":
```

**Builder must verify** before Section 3 wiring:
- Confirm `runtime.oracle.query(query_text, *, agent_id="", ...)` exists (AD-686 public alias for `_oracle_service`, verified at `src/probos/cognitive/oracle_service.py:285`).
- Confirm `runtime.episodic_memory.recall_for_agent(agent_id, query, k=...)` signature.
- Confirm `runtime.codebase_index.query(concept)` signature.
- Confirm `runtime.records_store.search(query)` — if absent, document the degradation and leave the branch defensive.
- Exact line where `IntentMessage` is built inside `agent_chat` so the `message_text` prepend lands AT the right seam.

---

## Revision (2026-05-14)

**Pass 1 review:** `prompts/Reviews/ad-725-dm-subintent-dispatch-review.md` — Verdict ⚠️ Conditional. One Required finding.

**Applied:**

- **Required #1 (`runtime.oracle_service` does not exist as a public attribute)**: global rename `runtime.oracle_service` → `runtime.oracle` throughout the prompt (Solution Overview hard-contract #4, Files-to-Modify live-grep note, Section 2 `_dispatch` oracle branch, Builder-verification footnote at the bottom of Section 2, test plan `_FakeRuntime` description, Verified-Against-Codebase footer). `runtime.oracle` is the AD-686 public alias for `cog.oracle_service` set at `src/probos/runtime.py:1537`; the `_oracle_service` private attribute is still used internally but is not a stable public surface. Method name also changed from `oracle.lookup(query)` to the real `oracle.query(query, agent_id=agent_id)` — verified async signature at `src/probos/cognitive/oracle_service.py:285` returns `list[OracleResult]`; the dispatcher's existing `_stringify` already handles list-of-dataclass return shape via the `repr()` else-branch (Recommended #4 covered by Recommended #4 deferral below).

**Recommended applied (in-scope hardening):**

- **Recommended #3 (silent no-op on wrong-method-name is a diagnostic trap)**: added `logger.info(...)` to all four `_dispatch` branches (`oracle` / `episodic` / `codebase` / `knowledge`) on the no-method path so the operator sees one line per dead branch at first DM that classifies to that lookup. Tier-2 informational only; no behavior change.

**Deferred (Recommended-tier, not blocking):**

- **Recommended #1 (cache strategy)**: no cache in v1 — documented as forward marker `AD-725-5` in the existing forward-markers list. The timeout cap (500ms) + default-OFF gating bound the worst-case latency cost; the classifier is regex (sub-millisecond). Acceptable.
- **Recommended #2 (Section 3 prepend anchor line)**: Builder follows the existing "grep `IntentMessage(intent=\"direct_message\"` within `agent_chat` body" instruction. Pinning a line number adds future drift risk; the function-scoped grep is cheap and precise.
- **Recommended #4 (Episode dataclass stringify)**: `recall_for_agent` returns `list[Episode]`; the dispatcher's existing `_stringify` falls through to `repr()` for non-str/dict items. Acceptable for v1 — readable enough for the LLM, and a clean forward marker (`AD-725-6`) when the operator wants `"- " + ep.text` row formatting. Captured in the forward markers list at next Builder pass.

**Self-check:** `oracle_service` is no longer referenced in the prompt body outside this Revision section; `lookup(query)` (the wrong method name) is also gone. Confirmed by grep below.
